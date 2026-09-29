import unittest

from savebridge.cityhash import cityhash64

# Reference values from Google's CityHash64 (v1.1) C++ implementation.
VECTORS = [
    (0, 0x9ae16a3b2f90404f),
    (1, 0xbe6056edf5e94b54),
    (3, 0x6cc1a093e8224428),
    (4, 0x05112b9e6277f665),
    (7, 0x0f95c16a7544a65b),
    (8, 0xdc480bbce8c737a7),
    (9, 0x39c3f10b05150cf4),
    (16, 0xfbb2740319962d9b),
    (17, 0xa55b9970b7b70074),
    (31, 0x333d9582fd0ddf99),
    (32, 0x0a9d86aa8d37da5c),
    (33, 0xb0b792ea4aa52827),
    (63, 0x832ef1104703e155),
    (64, 0x00e74408f26f0006),
    (65, 0x660af9e281226458),
    (127, 0x57d5ceb00369780c),
    (128, 0x3ce11b99a5b026e0),
    (129, 0x8e081729ad83209c),
    (1000, 0x4812080591c97f4c),
    (4097, 0x585a56ce3f3bc0e9),
]


class CityHashTest(unittest.TestCase):
    def test_reference_vectors(self):
        for n, expected in VECTORS:
            with self.subTest(length=n):
                data = bytes(i * 7 % 256 for i in range(n))
                self.assertEqual(cityhash64(data), expected)


if __name__ == '__main__':
    unittest.main()
