"""Tests for the UC hardware detection module.

Tests hardware and solver detection including:
- detect_hardware() returns a valid HardwareProfile with positive cores/RAM
- Graceful handling when psutil is missing (mock ImportError)
- cpu_count(logical=False) returning None defaults to 1 physical core
- detect_available_solvers() returns a list of solver names
- HardwareProfile validation (negative cores/RAM rejected)
- Default fallback values when psutil is unavailable
"""

from unittest.mock import MagicMock, patch

import pytest

from src.uc.hardware_detector import (
    HardwareProfile,
    _DEFAULT_AVAILABLE_RAM_GB,
    _DEFAULT_LOGICAL_CORES,
    _DEFAULT_PHYSICAL_CORES,
    _DEFAULT_TOTAL_RAM_GB,
    _detect_cpu_cores,
    _detect_ram,
    detect_available_solvers,
    detect_hardware,
)


# ======================================================================
# TestHardwareProfileValidation
# ======================================================================


class TestHardwareProfileValidation:
    """Tests that HardwareProfile validates its parameters on init."""

    def test_valid_profile_creation(self) -> None:
        """A HardwareProfile with valid parameters is created without error."""
        profile = HardwareProfile(
            physical_cores=4,
            logical_cores=8,
            available_ram_gb=16.0,
            total_ram_gb=32.0,
            available_solvers=["HiGHS_CMD", "PULP_CBC_CMD"],
            os_name="Darwin",
            architecture="arm64",
        )

        assert profile.physical_cores == 4
        assert profile.logical_cores == 8
        assert profile.available_ram_gb == 16.0
        assert profile.total_ram_gb == 32.0
        assert profile.available_solvers == ["HiGHS_CMD", "PULP_CBC_CMD"]
        assert profile.os_name == "Darwin"
        assert profile.architecture == "arm64"

    def test_default_profile_creation(self) -> None:
        """A HardwareProfile with all defaults is valid."""
        profile = HardwareProfile()

        assert profile.physical_cores == _DEFAULT_PHYSICAL_CORES
        assert profile.logical_cores == _DEFAULT_LOGICAL_CORES
        assert profile.available_ram_gb == _DEFAULT_AVAILABLE_RAM_GB
        assert profile.total_ram_gb == _DEFAULT_TOTAL_RAM_GB
        assert profile.available_solvers == []
        assert profile.os_name == ""
        assert profile.architecture == ""

    def test_rejects_zero_physical_cores(self) -> None:
        """physical_cores < 1 raises ValueError."""
        with pytest.raises(ValueError, match="physical_cores must be >= 1"):
            HardwareProfile(physical_cores=0)

    def test_rejects_negative_physical_cores(self) -> None:
        """Negative physical_cores raises ValueError."""
        with pytest.raises(ValueError, match="physical_cores must be >= 1"):
            HardwareProfile(physical_cores=-1)

    def test_rejects_zero_logical_cores(self) -> None:
        """logical_cores < 1 raises ValueError."""
        with pytest.raises(ValueError, match="logical_cores must be >= 1"):
            HardwareProfile(logical_cores=0)

    def test_rejects_negative_available_ram(self) -> None:
        """Negative available_ram_gb raises ValueError."""
        with pytest.raises(ValueError, match="available_ram_gb must be non-negative"):
            HardwareProfile(available_ram_gb=-1.0)

    def test_rejects_negative_total_ram(self) -> None:
        """Negative total_ram_gb raises ValueError."""
        with pytest.raises(ValueError, match="total_ram_gb must be non-negative"):
            HardwareProfile(total_ram_gb=-1.0)

    def test_zero_ram_is_valid(self) -> None:
        """Zero RAM values are accepted (non-negative constraint)."""
        profile = HardwareProfile(available_ram_gb=0.0, total_ram_gb=0.0)
        assert profile.available_ram_gb == 0.0
        assert profile.total_ram_gb == 0.0

    def test_available_solvers_default_is_empty_list(self) -> None:
        """Default available_solvers is an independent empty list."""
        p1 = HardwareProfile()
        p2 = HardwareProfile()
        p1.available_solvers.append("CBC")
        # Mutation of p1 must not affect p2 (mutable default safety)
        assert p2.available_solvers == []


# ======================================================================
# TestDetectHardware
# ======================================================================


class TestDetectHardware:
    """Tests that detect_hardware() returns a valid HardwareProfile."""

    def test_returns_hardware_profile(self) -> None:
        """detect_hardware() returns a HardwareProfile instance."""
        profile = detect_hardware()
        assert isinstance(profile, HardwareProfile)

    def test_positive_physical_cores(self) -> None:
        """Detected physical cores must be >= 1."""
        profile = detect_hardware()
        assert profile.physical_cores >= 1

    def test_positive_logical_cores(self) -> None:
        """Detected logical cores must be >= 1."""
        profile = detect_hardware()
        assert profile.logical_cores >= 1

    def test_positive_ram(self) -> None:
        """Detected RAM values must be positive."""
        profile = detect_hardware()
        assert profile.available_ram_gb > 0
        assert profile.total_ram_gb > 0

    def test_os_name_is_nonempty(self) -> None:
        """OS name should be a non-empty string."""
        profile = detect_hardware()
        assert isinstance(profile.os_name, str)
        assert len(profile.os_name) > 0

    def test_architecture_is_nonempty(self) -> None:
        """Architecture should be a non-empty string."""
        profile = detect_hardware()
        assert isinstance(profile.architecture, str)
        assert len(profile.architecture) > 0

    def test_available_solvers_is_list(self) -> None:
        """available_solvers should be a list of strings."""
        profile = detect_hardware()
        assert isinstance(profile.available_solvers, list)
        for solver in profile.available_solvers:
            assert isinstance(solver, str)

    def test_logical_cores_gte_physical_cores(self) -> None:
        """Logical cores should be >= physical cores."""
        profile = detect_hardware()
        assert profile.logical_cores >= profile.physical_cores

    def test_total_ram_gte_available_ram(self) -> None:
        """Total RAM should be >= available RAM."""
        profile = detect_hardware()
        assert profile.total_ram_gb >= profile.available_ram_gb


# ======================================================================
# TestDetectHardwareWithoutPsutil
# ======================================================================


class TestDetectHardwareWithoutPsutil:
    """Tests graceful fallback when psutil is not available."""

    def test_fallback_when_psutil_missing(self) -> None:
        """detect_hardware() returns conservative defaults without psutil."""
        with patch(
            "src.uc.hardware_detector._PSUTIL_AVAILABLE", False
        ):
            profile = detect_hardware()

        assert isinstance(profile, HardwareProfile)
        assert profile.physical_cores == _DEFAULT_PHYSICAL_CORES
        assert profile.available_ram_gb == _DEFAULT_AVAILABLE_RAM_GB
        assert profile.total_ram_gb == _DEFAULT_TOTAL_RAM_GB

    def test_fallback_still_has_os_info(self) -> None:
        """OS name and architecture are still detected without psutil."""
        with patch(
            "src.uc.hardware_detector._PSUTIL_AVAILABLE", False
        ):
            profile = detect_hardware()

        assert len(profile.os_name) > 0
        assert len(profile.architecture) > 0

    def test_fallback_still_detects_solvers(self) -> None:
        """Solver detection works independently of psutil."""
        with patch(
            "src.uc.hardware_detector._PSUTIL_AVAILABLE", False
        ):
            profile = detect_hardware()

        # Solver detection uses PuLP, not psutil — should still work
        assert isinstance(profile.available_solvers, list)

    def test_cpu_detection_without_psutil_uses_os_cpu_count(self) -> None:
        """Without psutil, _detect_cpu_cores() uses os.cpu_count() for logical."""
        with patch(
            "src.uc.hardware_detector._PSUTIL_AVAILABLE", False
        ), patch("os.cpu_count", return_value=4):
            physical, logical = _detect_cpu_cores()

        # Physical cores default to 1 without psutil
        assert physical == _DEFAULT_PHYSICAL_CORES
        # Logical cores come from os.cpu_count()
        assert logical == 4

    def test_cpu_detection_without_psutil_os_cpu_count_none(self) -> None:
        """Without psutil and os.cpu_count() returning None, uses defaults."""
        with patch(
            "src.uc.hardware_detector._PSUTIL_AVAILABLE", False
        ), patch("os.cpu_count", return_value=None):
            physical, logical = _detect_cpu_cores()

        assert physical == _DEFAULT_PHYSICAL_CORES
        assert logical == _DEFAULT_LOGICAL_CORES

    def test_ram_detection_without_psutil(self) -> None:
        """Without psutil, _detect_ram() returns conservative defaults."""
        with patch(
            "src.uc.hardware_detector._PSUTIL_AVAILABLE", False
        ):
            available, total = _detect_ram()

        assert available == _DEFAULT_AVAILABLE_RAM_GB
        assert total == _DEFAULT_TOTAL_RAM_GB


# ======================================================================
# TestCpuCountNoneHandling
# ======================================================================


class TestCpuCountNoneHandling:
    """Tests that cpu_count(logical=False) returning None defaults to 1."""

    def test_physical_cores_none_defaults_to_1(self) -> None:
        """cpu_count(logical=False) returning None defaults to 1 core."""
        mock_psutil = MagicMock()
        mock_psutil.cpu_count.side_effect = (
            lambda logical=True: None if not logical else 4
        )

        with patch(
            "src.uc.hardware_detector._PSUTIL_AVAILABLE", True
        ), patch(
            "src.uc.hardware_detector.psutil", mock_psutil, create=True
        ):
            physical, logical = _detect_cpu_cores()

        assert physical == _DEFAULT_PHYSICAL_CORES
        assert logical == 4

    def test_both_counts_none_defaults(self) -> None:
        """Both cpu_count calls returning None default gracefully."""
        mock_psutil = MagicMock()
        mock_psutil.cpu_count.return_value = None

        with patch(
            "src.uc.hardware_detector._PSUTIL_AVAILABLE", True
        ), patch(
            "src.uc.hardware_detector.psutil", mock_psutil, create=True
        ):
            physical, logical = _detect_cpu_cores()

        assert physical == _DEFAULT_PHYSICAL_CORES
        # When logical is None, it defaults to physical
        assert logical == _DEFAULT_PHYSICAL_CORES

    def test_logical_none_defaults_to_physical(self) -> None:
        """cpu_count(logical=True) returning None defaults to physical count."""
        mock_psutil = MagicMock()
        mock_psutil.cpu_count.side_effect = (
            lambda logical=True: None if logical else 8
        )

        with patch(
            "src.uc.hardware_detector._PSUTIL_AVAILABLE", True
        ), patch(
            "src.uc.hardware_detector.psutil", mock_psutil, create=True
        ):
            physical, logical = _detect_cpu_cores()

        assert physical == 8
        # Logical defaults to physical when None
        assert logical == 8

    def test_detect_hardware_handles_cpu_none(self) -> None:
        """Full detect_hardware() handles cpu_count returning None."""
        mock_psutil = MagicMock()
        mock_psutil.cpu_count.side_effect = (
            lambda logical=True: None if not logical else 2
        )
        mock_mem = MagicMock()
        mock_mem.total = 8 * (1024 ** 3)
        mock_mem.available = 4 * (1024 ** 3)
        mock_psutil.virtual_memory.return_value = mock_mem

        with patch(
            "src.uc.hardware_detector._PSUTIL_AVAILABLE", True
        ), patch(
            "src.uc.hardware_detector.psutil", mock_psutil, create=True
        ):
            profile = detect_hardware()

        assert profile.physical_cores == _DEFAULT_PHYSICAL_CORES
        assert profile.logical_cores == 2
        assert profile.available_ram_gb == pytest.approx(4.0, abs=0.1)
        assert profile.total_ram_gb == pytest.approx(8.0, abs=0.1)


# ======================================================================
# TestDetectAvailableSolvers
# ======================================================================


class TestDetectAvailableSolvers:
    """Tests that detect_available_solvers() returns solver name list."""

    def test_returns_list(self) -> None:
        """detect_available_solvers() returns a list."""
        solvers = detect_available_solvers()
        assert isinstance(solvers, list)

    def test_returns_strings(self) -> None:
        """All entries in the solver list are strings."""
        solvers = detect_available_solvers()
        for solver in solvers:
            assert isinstance(solver, str)

    def test_cbc_typically_available(self) -> None:
        """PULP_CBC_CMD should be available (bundled with PuLP)."""
        solvers = detect_available_solvers()
        assert "PULP_CBC_CMD" in solvers

    def test_returns_sorted_list(self) -> None:
        """Solver list is returned in sorted order."""
        solvers = detect_available_solvers()
        assert solvers == sorted(solvers)

    def test_handles_pulp_exception(self) -> None:
        """Returns empty list when PuLP listSolvers raises an exception."""
        with patch(
            "pulp.listSolvers",
            side_effect=Exception("PuLP not available"),
        ):
            solvers = detect_available_solvers()

        assert solvers == []

    def test_mock_solver_list(self) -> None:
        """Correctly wraps and sorts pulp.listSolvers output."""
        mock_solvers = ["GLPK_CMD", "PULP_CBC_CMD", "HiGHS_CMD"]
        with patch(
            "pulp.listSolvers",
            return_value=mock_solvers,
        ):
            solvers = detect_available_solvers()

        # Should be sorted
        assert solvers == ["GLPK_CMD", "HiGHS_CMD", "PULP_CBC_CMD"]


# ======================================================================
# TestDetectRam
# ======================================================================


class TestDetectRam:
    """Tests for RAM detection helper."""

    def test_ram_with_mock_psutil(self) -> None:
        """_detect_ram() returns correct values from mocked psutil."""
        mock_psutil = MagicMock()
        mock_mem = MagicMock()
        mock_mem.total = 16 * (1024 ** 3)  # 16 GB
        mock_mem.available = 8 * (1024 ** 3)  # 8 GB
        mock_psutil.virtual_memory.return_value = mock_mem

        with patch(
            "src.uc.hardware_detector._PSUTIL_AVAILABLE", True
        ), patch(
            "src.uc.hardware_detector.psutil", mock_psutil, create=True
        ):
            available, total = _detect_ram()

        assert available == pytest.approx(8.0, abs=0.1)
        assert total == pytest.approx(16.0, abs=0.1)

    def test_ram_psutil_exception(self) -> None:
        """_detect_ram() returns defaults on psutil exception."""
        mock_psutil = MagicMock()
        mock_psutil.virtual_memory.side_effect = RuntimeError("fail")

        with patch(
            "src.uc.hardware_detector._PSUTIL_AVAILABLE", True
        ), patch(
            "src.uc.hardware_detector.psutil", mock_psutil, create=True
        ):
            available, total = _detect_ram()

        assert available == _DEFAULT_AVAILABLE_RAM_GB
        assert total == _DEFAULT_TOTAL_RAM_GB
