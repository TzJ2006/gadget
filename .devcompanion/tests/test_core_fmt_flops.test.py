"""Tests for fmt_flops"""
# import from source module


class TestFmtFlops:
    """Converts a raw FLOPS (floating-point operations per second) value into a formatted string with the most appropriate unit (PFLOPS, TFLOPS, GFLOPS, MFLOPS, KFLOPS, or FLOPS). Returns formatted value with comma separators and two decimal places."""

    def test_valid_inputs(self):
        """Should accept valid inputs and return expected output."""
        # flops (float): The raw floating-point operations per second value to format
        # Expected: Formatted FLOPS string with appropriate unit suffix and thousands separators (e.g., '1.23 TFLOPS/s')
        assert False  # TODO: implement
