# Copyright 2009 The Go Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be found in LICENSE-go.
"""A port of Go's ``sort.Sort`` (pattern-defeating quicksort, Go 1.19 and later).

Go's sort is not stable and apimachinery sorts requirements with it, so equal keys come out
in Go's order only under the same algorithm.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

_UNKNOWN = 0
_INCREASING = 1
_DECREASING = 2
_MASK = (1 << 64) - 1


def go_sort(data: list[T], less_than: Callable[[T, T], bool]) -> list[T]:
    """Sort ``data`` in place, ordering equal elements exactly as Go's ``sort.Sort`` would."""

    def less(i: int, j: int) -> bool:
        return less_than(data[i], data[j])

    def swap(i: int, j: int) -> None:
        data[i], data[j] = data[j], data[i]

    n = len(data)
    if n <= 1:
        return data

    def insertion_sort(a: int, b: int) -> None:
        for i in range(a + 1, b):
            j = i
            while j > a and less(j, j - 1):
                swap(j, j - 1)
                j -= 1

    def sift_down(lo: int, hi: int, first: int) -> None:
        root = lo
        while True:
            child = 2 * root + 1
            if child >= hi:
                return
            if child + 1 < hi and less(first + child, first + child + 1):
                child += 1
            if not less(first + root, first + child):
                return
            swap(first + root, first + child)
            root = child

    def heap_sort(a: int, b: int) -> None:
        first = a
        hi = b - a
        for i in range((hi - 1) // 2, -1, -1):
            sift_down(i, hi, first)
        for i in range(hi - 1, -1, -1):
            swap(first, first + i)
            sift_down(0, i, first)

    def partition(a: int, b: int, pivot: int) -> tuple[int, bool]:
        swap(a, pivot)
        i, j = a + 1, b - 1
        while i <= j and less(i, a):
            i += 1
        while i <= j and not less(j, a):
            j -= 1
        if i > j:
            swap(j, a)
            return j, True
        swap(i, j)
        i += 1
        j -= 1
        while True:
            while i <= j and less(i, a):
                i += 1
            while i <= j and not less(j, a):
                j -= 1
            if i > j:
                break
            swap(i, j)
            i += 1
            j -= 1
        swap(j, a)
        return j, False

    def partition_equal(a: int, b: int, pivot: int) -> int:
        swap(a, pivot)
        i, j = a + 1, b - 1
        while True:
            while i <= j and not less(a, i):
                i += 1
            while i <= j and less(a, j):
                j -= 1
            if i > j:
                break
            swap(i, j)
            i += 1
            j -= 1
        return i

    def partial_insertion_sort(a: int, b: int) -> bool:
        max_steps = 5
        shortest_shifting = 50
        i = a + 1
        for _ in range(max_steps):
            while i < b and not less(i, i - 1):
                i += 1
            if i == b:
                return True
            if b - a < shortest_shifting:
                return False
            swap(i, i - 1)
            if i - a >= 2:
                k = i - 1
                while k >= 1:
                    if not less(k, k - 1):
                        break
                    swap(k, k - 1)
                    k -= 1
            if b - i >= 2:
                k = i + 1
                while k < b:
                    if not less(k, k - 1):
                        break
                    swap(k, k - 1)
                    k += 1
        return False

    def break_patterns(a: int, b: int) -> None:
        length = b - a
        if length >= 8:
            random = length
            modulus = 1 << length.bit_length()
            base = a + (length // 4) * 2
            for idx in range(base - 1, base + 2):
                random ^= (random << 13) & _MASK
                random ^= random >> 7
                random ^= (random << 17) & _MASK
                other = random & (modulus - 1)
                if other >= length:
                    other -= length
                swap(idx, a + other)

    swaps = [0]

    def order2(a: int, b: int) -> tuple[int, int]:
        if less(b, a):
            swaps[0] += 1
            return b, a
        return a, b

    def median(a: int, b: int, c: int) -> int:
        a, b = order2(a, b)
        b, c = order2(b, c)
        a, b = order2(a, b)
        return b

    def median_adjacent(a: int) -> int:
        return median(a - 1, a, a + 1)

    def choose_pivot(a: int, b: int) -> tuple[int, int]:
        shortest_ninther = 50
        max_swaps = 4 * 3
        length = b - a
        swaps[0] = 0
        i = a + length // 4 * 1
        j = a + length // 4 * 2
        k = a + length // 4 * 3
        if length >= 8:
            if length >= shortest_ninther:
                i = median_adjacent(i)
                j = median_adjacent(j)
                k = median_adjacent(k)
            j = median(i, j, k)
        if swaps[0] == 0:
            return j, _INCREASING
        if swaps[0] == max_swaps:
            return j, _DECREASING
        return j, _UNKNOWN

    def reverse_range(a: int, b: int) -> None:
        i, j = a, b - 1
        while i < j:
            swap(i, j)
            i += 1
            j -= 1

    def pdqsort(a: int, b: int, limit: int) -> None:
        max_insertion = 12
        was_balanced = True
        was_partitioned = True
        while True:
            length = b - a
            if length <= max_insertion:
                insertion_sort(a, b)
                return
            if limit == 0:
                heap_sort(a, b)
                return
            if not was_balanced:
                break_patterns(a, b)
                limit -= 1
            pivot, hint = choose_pivot(a, b)
            if hint == _DECREASING:
                reverse_range(a, b)
                pivot = (b - 1) - (pivot - a)
                hint = _INCREASING
            if was_balanced and was_partitioned and hint == _INCREASING:
                if partial_insertion_sort(a, b):
                    return
            if a > 0 and not less(a - 1, pivot):
                a = partition_equal(a, b, pivot)
                continue
            mid, already = partition(a, b, pivot)
            was_partitioned = already
            left_len, right_len = mid - a, b - mid
            balance_threshold = length // 8
            if left_len < right_len:
                was_balanced = left_len >= balance_threshold
                pdqsort(a, mid, limit)
                a = mid + 1
            else:
                was_balanced = right_len >= balance_threshold
                pdqsort(mid + 1, b, limit)
                b = mid

    pdqsort(0, n, n.bit_length())
    return data
