"""Throwaway: a deliberately failing test to prove the gate. This branch is deleted after the proof."""
import unittest


class TestGateProof(unittest.TestCase):
    def test_fails_on_purpose(self):
        self.assertEqual(1, 2)
