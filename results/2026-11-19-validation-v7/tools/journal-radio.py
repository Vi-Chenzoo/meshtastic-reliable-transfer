#!/usr/bin/env python3
"""Journal RADIO du firmware d'ESSAI v4 (heltec-v4-projet-essai) : vider avant un essai, relire APRÈS, par USB.

Le boîtier note, à la microseconde, ce que fait sa radio (mise en file, attente, début et fin d'émission, paquets reçus) dans des
tampons en mémoire ; rien n'est envoyé au PC pendant l'essai (un affichage USB bloquerait le boîtier et fausserait la mesure).
Copyright (C) 2026 SoCodeIA et Vincent PERRIN — GPL v3.

    python3 outils/journal-radio.py vider --port /dev/serial/by-id/...                 # AVANT l'essai, sur CHAQUE boîtier
    python3 outils/journal-radio.py lire  --port /dev/serial/by-id/... --sortie essais/.../boitier1.json     # APRÈS, sur CHAQUE boîtier
    python3 outils/analyse-journal-radio.py boitier1.json boitier2.json            # les deux ensemble : surdité, attente, temps d'émission
Le vidage de 2000 événements demande environ 150 échanges USB (13 enregistrements par réponse) : compter une dizaine de secondes.
Ne lance qu'un outil par port ; le firmware ordinaire répond par rien (l'outil le dit au bout de 10 s).
"""
import argparse, json, os, sys, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_journal_radio as lj

PRIVATE_APP = 256
ORDRE = 0x0C


def main():
    a = argparse.ArgumentParser(description="Journal radio du firmware d'essai v4.")
    a.add_argument("action", choices=("vider", "entete", "lire", "cw", "rencontre", "oublier"))
    a.add_argument("--valeur", type=int, default=0, help="cw : supplément de fenêtre de contention pour les trames de données, 0 (défaut du firmware) à 2 ; rencontre : 1 = réponse immédiate à un voisin ESP-NOW nouveau (défaut), 0 = non ; oublier : 0 = oublier les voisins ESP-NOW, 1 = les oublier ET dire bonjour dans les 3 s (comme un boîtier qui arrive)")
    a.add_argument("--port", help="port USB (défaut : trouvé seul ; préférer /dev/serial/by-id/…)")
    a.add_argument("--hote", help="adresse réseau du boîtier (au lieu de l'USB)")
    a.add_argument("--sortie", help="lire : fichier JSON à écrire")
    a.add_argument("--attente", type=float, default=4.0, help="secondes à attendre une réponse avant de redemander (3 essais)")
    args = a.parse_args()
    if args.action == "lire" and not args.sortie:
        a.error("--sortie est obligatoire pour lire")

    import meshtastic.serial_interface, meshtastic.tcp_interface
    from pubsub import pub
    iface = (meshtastic.tcp_interface.TCPInterface(hostname=args.hote) if args.hote else meshtastic.serial_interface.SerialInterface(devPath=args.port))
    moi = iface.myInfo.my_node_num
    recues, evenement = [], threading.Condition()

    def recu(packet, interface):                       # fonction nommée : pypubsub ne garde qu'une référence faible
        d = packet.get("decoded", {})
        c = d.get("payload", b"")
        if d.get("portnum") == "PRIVATE_APP" and c[:1] == bytes([ORDRE]) and len(c) >= 2 and packet.get("from") == moi:
            with evenement:
                recues.append((chr(c[1]), bytes(c[2:])))
                evenement.notify_all()

    pub.subscribe(recu, "meshtastic.receive")

    def demander(charge, etat_attendu, verifie=lambda b: True):
        for _ in range(3):
            n0 = len(recues)
            iface.sendData(charge, destinationId=moi, portNum=PRIVATE_APP, wantAck=False)
            fin = time.time() + args.attente
            with evenement:
                while time.time() < fin:
                    for etat, corps in recues[n0:]:
                        if etat == "E":
                            raise RuntimeError("refus du boîtier : " + corps.decode("utf-8", "replace"))
                        if etat == etat_attendu and verifie(corps):
                            return corps
                    evenement.wait(0.2)
        raise TimeoutError("pas de réponse du boîtier : le firmware d'ESSAI v4 (heltec-v4-projet-essai) est-il installé ?")

    code = 0
    try:
        print(f"boîtier !{moi:08x}")
        if args.action == "vider":
            demander(bytes([ORDRE, ord("Z")]), "K")
            print("journal vidé")
        elif args.action in ("rencontre", "oublier"):   # firmware d'essai v8 : ordres 'B' et 'O'
            if args.valeur not in (0, 1):
                raise RuntimeError("--valeur : 0 ou 1")
            print(demander(bytes([ORDRE, ord("B" if args.action == "rencontre" else "O"), args.valeur]), "K").decode("utf-8", "replace"))
        elif args.action == "cw":
            if not 0 <= args.valeur <= 2:
                raise RuntimeError("--valeur : 0 à 2")
            print(demander(bytes([ORDRE, ord("W"), args.valeur]), "K").decode("utf-8", "replace"))
        else:
            h = lj.decoder_entete(demander(bytes([ORDRE, ord("H")]), "H"))
            print(f"en-tête : SF{h['sf']} BW{h['bw_khz']:g} CR4/{h['cr']} préambule {h['preambule']}, preset {lj.PRESETS.get(h['preset'], h['preset'])}, "
                  f"{h['ecrits_logiciel']} événements du logiciel écrits (tampon {h['cap_logiciel']}), {h['ecrits_isr']} interruptions (tampon {h['cap_isr']})")
            if args.action == "lire":
                if not h["cap_logiciel"]:
                    raise RuntimeError("journal radio éteint dans ce firmware (tas interne trop juste au démarrage ?)")
                sortie = {"format": 1, "boitier": f"!{moi:08x}", "relu_le": time.strftime("%Y-%m-%d %H:%M:%S"), "entete": h, "anneaux": {}}
                for anneau, nom in ((0, "logiciel"), (1, "isr")):
                    liste, decalage, total = [], 0, None
                    while total is None or decalage < total:
                        corps = demander(bytes([ORDRE, ord("J"), anneau]) + decalage.to_bytes(2, "big"), "J",
                                         lambda b, an=anneau, de=decalage: len(b) >= 5 and b[0] == an and int.from_bytes(b[1:3], "big") == de)
                        _, _, total, enregs = lj.decoder_morceau(corps)
                        if not enregs:
                            break
                        liste += enregs
                        decalage += len(enregs)
                    sortie["anneaux"][nom] = liste
                    print(f"{nom} : {len(liste)} enregistrements relus")
                ecrits = h["ecrits_logiciel"] - len(sortie["anneaux"]["logiciel"])
                if ecrits > 0:
                    print(f"ATTENTION : {ecrits} événements du logiciel ont été écrasés (tampon trop petit pour l'essai)")
                with open(args.sortie, "w", encoding="utf-8") as f:
                    json.dump(sortie, f)
                print(f"écrit : {args.sortie}")
    except (RuntimeError, TimeoutError) as e:
        print(e)
        code = 1
    finally:
        fermeture = threading.Thread(target=iface.close, daemon=True)
        fermeture.start()
        fermeture.join(5)
    return code


if __name__ == "__main__":
    sys.exit(main())
