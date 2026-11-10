// Copyright (C) 2026 SoCodeIA and Vincent PERRIN. Licensed under the GNU General Public License version 3 (LICENSE).
// The few Unity assertions used by test_main.cpp, so that the test builds with a plain C++ compiler. In the
// Meshtastic firmware tree the same test runs under PlatformIO with the real Unity.
#pragma once
#include <cmath>
#include <cstdio>
#include <cstdlib>
static int unity_failures = 0;
#define UNITY_BEGIN() ((void)0)
#define UNITY_END() (printf("%s: %d failure(s)\n", unity_failures ? "FAIL" : "OK", unity_failures), unity_failures ? 1 : 0)
#define RUN_TEST(f) do { printf("== %s\n", #f); fflush(stdout); f(); } while (0)
#define U_FAIL(m) do { printf("  FAIL line %d: %s\n", __LINE__, m); unity_failures++; return; } while (0)
#define TEST_ASSERT_TRUE_MESSAGE(c, m) do { if (!(c)) U_FAIL(m); } while (0)
#define TEST_ASSERT_TRUE(c) TEST_ASSERT_TRUE_MESSAGE(c, #c)
#define TEST_ASSERT_FALSE(c) TEST_ASSERT_TRUE_MESSAGE(!(c), #c)
#define TEST_ASSERT_EQUAL_MESSAGE(a, b, m) TEST_ASSERT_TRUE_MESSAGE((long long)(a) == (long long)(b), m)
#define TEST_ASSERT_EQUAL_INT_MESSAGE TEST_ASSERT_EQUAL_MESSAGE
#define TEST_ASSERT_EQUAL_UINT_MESSAGE TEST_ASSERT_EQUAL_MESSAGE
#define TEST_ASSERT_EQUAL_CHAR_MESSAGE TEST_ASSERT_EQUAL_MESSAGE
#define TEST_ASSERT_EQUAL_UINT(a, b) TEST_ASSERT_EQUAL_MESSAGE(a, b, #a " == " #b)
#define TEST_ASSERT_EQUAL_HEX(a, b) TEST_ASSERT_EQUAL_MESSAGE(a, b, #a " == " #b)
#define TEST_ASSERT_LESS_THAN_MESSAGE(lim, x, m) TEST_ASSERT_TRUE_MESSAGE((x) < (lim), m)
#define TEST_ASSERT_EQUAL_DOUBLE_MESSAGE(a, b, m) TEST_ASSERT_TRUE_MESSAGE((double)(a) == (double)(b), m)
#define TEST_ASSERT_EQUAL_DOUBLE(a, b) TEST_ASSERT_EQUAL_DOUBLE_MESSAGE(a, b, #a " == " #b)
#define TEST_ASSERT_EQUAL_UINT16_MESSAGE TEST_ASSERT_EQUAL_MESSAGE
#define TEST_ASSERT_EQUAL_HEX32_MESSAGE TEST_ASSERT_EQUAL_MESSAGE
#define TEST_ASSERT_EQUAL_HEX32(a, b) TEST_ASSERT_EQUAL_MESSAGE(a, b, #a " == " #b)
#define TEST_ASSERT_EQUAL_HEX8(a, b) TEST_ASSERT_EQUAL_MESSAGE(a, b, #a " == " #b)
#define TEST_ASSERT_EQUAL_INT(a, b) TEST_ASSERT_EQUAL_MESSAGE(a, b, #a " == " #b)
#define TEST_ASSERT_EQUAL(a, b) TEST_ASSERT_EQUAL_MESSAGE(a, b, #a " == " #b)
