"""Load interconnection data from YAML into UC-ready format.

Reads inter-regional interconnection definitions from a YAML file
(``data/reference/interconnections.yaml``), validates required fields,
and produces a list of :class:`~src.uc.models.Interconnection` objects
for use in unit commitment solving with transmission capacity constraints.

Usage::

    from src.uc.interconnection_loader import InterconnectionLoader

    loader = InterconnectionLoader()
    interconnections = loader.load("data/reference/interconnections.yaml")
"""

from typing import List

import yaml

from src.uc.models import Interconnection
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

# Required fields in each interconnection record
_REQUIRED_FIELDS = ("id", "from_region", "to_region", "capacity_mw")


class InterconnectionLoader:
    """Load interconnection data from YAML.

    Reads interconnection records from a YAML file, validates that all
    required fields are present, and returns a list of
    :class:`Interconnection` instances.
    """

    def __init__(self) -> None:
        """Initialize the InterconnectionLoader."""
        logger.info("InterconnectionLoader initialized")

    def load(self, yaml_path: str) -> List[Interconnection]:
        """Load interconnection definitions from a YAML file.

        Reads the ``interconnections`` key from the YAML document and
        creates an :class:`Interconnection` for each record. Validates
        that all required fields (``id``, ``from_region``, ``to_region``,
        ``capacity_mw``) are present in each record.

        Args:
            yaml_path: Path to the interconnections YAML file.

        Returns:
            List of :class:`Interconnection` objects.

        Raises:
            FileNotFoundError: If *yaml_path* does not exist.
            ValueError: If a required field is missing from any record.
        """
        logger.info("Loading interconnections from YAML: %s", yaml_path)

        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        interconnections: List[Interconnection] = []

        for idx, record in enumerate(data.get("interconnections", [])):
            # Validate required fields
            for field_name in _REQUIRED_FIELDS:
                if field_name not in record:
                    raise ValueError(
                        f"Interconnection record {idx} is missing "
                        f"required field '{field_name}'"
                    )

            ic = Interconnection(
                id=record["id"],
                name_en=record.get("name_en", ""),
                from_region=record["from_region"],
                to_region=record["to_region"],
                capacity_mw=float(record["capacity_mw"]),
                type=record.get("type", "AC"),
            )
            interconnections.append(ic)

        logger.info(
            "Loaded %d interconnections from %s",
            len(interconnections),
            yaml_path,
        )
        return interconnections
