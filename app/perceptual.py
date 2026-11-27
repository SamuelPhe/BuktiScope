from __future__ import annotations

import numpy as np
from PIL import Image

HASH_SIZE = 8
HIGHFREQ_FACTOR = 4
MIN_IMAGE_STDDEV = 8.0


def _dct_matrix(size: int) -> np.ndarray:
    """Build an orthonormal DCT-II transform matrix."""
    positions = np.arange(size, dtype=np.float32)
    frequencies = positions[:, None]
    samples = positions[None, :]
    matrix = np.cos((np.pi / size) * (samples + 0.5) * frequencies)
    matrix[0, :] *= np.sqrt(1.0 / size)
    matrix[1:, :] *= np.sqrt(2.0 / size)
    return matrix


_DCT = _dct_matrix(HASH_SIZE * HIGHFREQ_FACTOR)


def perceptual_hash(image: Image.Image) -> str | None:
    """Return a 64-bit pHash; None for nearly uniform images.

    This is a similarity fingerprint, not a manipulation detector.
    """
    grayscale = image.convert("L")
    pixels = np.asarray(
        grayscale.resize(
            (HASH_SIZE * HIGHFREQ_FACTOR, HASH_SIZE * HIGHFREQ_FACTOR),
            Image.Resampling.LANCZOS,
        ),
        dtype=np.float32,
    )
    if float(pixels.std()) < MIN_IMAGE_STDDEV:
        return None

    transformed = _DCT @ pixels @ _DCT.T
    low_frequencies = transformed[:HASH_SIZE, :HASH_SIZE].copy()
    median = float(np.median(low_frequencies.flatten()[1:]))
    bits = (low_frequencies.flatten() > median)

    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return f"{value:016x}"


def hamming_distance(first: str, second: str) -> int:
    """Count the differing bits in two 64-bit hexadecimal hashes."""
    return (int(first, 16) ^ int(second, 16)).bit_count()
