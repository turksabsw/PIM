"""GS1 Standards Validation Utilities

This module provides comprehensive validation and generation utilities for
GS1 standard identifiers used in global product and location identification:

- GTIN-8: 8-digit Global Trade Item Number (EAN-8)
- GTIN-12: 12-digit Global Trade Item Number (UPC-A)
- GTIN-13: 13-digit Global Trade Item Number (EAN-13)
- GTIN-14: 14-digit Global Trade Item Number (ITF-14)
- GLN: Global Location Number (13-digit location identifier)
- SSCC: Serial Shipping Container Code (18-digit logistics unit identifier)
- GSIN: Global Shipment Identification Number (17-digit)
- GINC: Global Identification Number for Consignment (variable length)

All validation follows the official GS1 General Specifications:
https://www.gs1.org/standards/barcodes-epcrfid-id-keys/gs1-general-specifications

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple, List, Dict, Any


class GTINType(Enum):
    """GTIN format types."""
    GTIN_8 = 8
    GTIN_12 = 12
    GTIN_13 = 13
    GTIN_14 = 14


class GS1IdentifierType(Enum):
    """GS1 identifier types."""
    GTIN = "gtin"
    GLN = "gln"
    SSCC = "sscc"
    GSIN = "gsin"
    GINC = "ginc"


@dataclass
class ValidationResult:
    """Result of a GS1 identifier validation."""
    is_valid: bool
    identifier: str
    identifier_type: Optional[str] = None
    normalized: Optional[str] = None
    check_digit: Optional[str] = None
    errors: Optional[List[str]] = None
    warnings: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "is_valid": self.is_valid,
            "identifier": self.identifier,
            "identifier_type": self.identifier_type,
            "normalized": self.normalized,
            "check_digit": self.check_digit,
            "errors": self.errors or [],
            "warnings": self.warnings or [],
        }


# =============================================================================
# Check Digit Calculation (GS1 Standard Algorithm)
# =============================================================================

def calculate_check_digit(digits: str) -> str:
    """Calculate GS1 check digit using the standard modulo-10 algorithm.

    The GS1 check digit algorithm:
    1. Starting from the rightmost digit (before check digit position),
       multiply alternating digits by 3 and 1
    2. Sum all products
    3. Check digit = (10 - (sum % 10)) % 10

    This algorithm works for all GS1 keys: GTIN-8/12/13/14, GLN, SSCC.

    Args:
        digits: String of digits WITHOUT the check digit

    Returns:
        Single digit character representing the check digit

    Example:
        >>> calculate_check_digit("629104150021")  # GTIN-13 without check
        '3'
    """
    if not digits.isdigit():
        raise ValueError("Input must contain only digits")

    # Pad to even length for consistent processing
    # GS1 algorithm: from right, positions are numbered 1, 2, 3, ...
    # Odd positions (1, 3, 5, ...) multiply by 3
    # Even positions (2, 4, 6, ...) multiply by 1

    total = 0
    for i, digit in enumerate(reversed(digits)):
        multiplier = 3 if i % 2 == 0 else 1
        total += int(digit) * multiplier

    check_digit = (10 - (total % 10)) % 10
    return str(check_digit)


def verify_check_digit(identifier: str) -> bool:
    """Verify the check digit of a GS1 identifier.

    Works for all GS1 standard identifiers (GTIN, GLN, SSCC, etc.)

    Args:
        identifier: Complete GS1 identifier including check digit

    Returns:
        True if check digit is valid, False otherwise
    """
    if not identifier.isdigit() or len(identifier) < 2:
        return False

    data_digits = identifier[:-1]
    expected_check = calculate_check_digit(data_digits)
    actual_check = identifier[-1]

    return expected_check == actual_check


# =============================================================================
# GTIN Validation
# =============================================================================

def validate_gtin(gtin: str, expected_type: Optional[GTINType] = None) -> ValidationResult:
    """Validate a GTIN (Global Trade Item Number).

    Validates GTIN-8, GTIN-12, GTIN-13, and GTIN-14 formats according to
    GS1 General Specifications.

    Args:
        gtin: GTIN string to validate (may contain spaces/dashes)
        expected_type: Optional specific GTIN type to validate against

    Returns:
        ValidationResult with validation details

    Examples:
        >>> result = validate_gtin("4006381333931")  # Valid GTIN-13
        >>> result.is_valid
        True
        >>> result = validate_gtin("12345678")  # Invalid check digit
        >>> result.is_valid
        False
    """
    errors = []
    warnings = []

    # Normalize: remove spaces, dashes, and leading/trailing whitespace
    original = gtin
    gtin = str(gtin).strip().replace(" ", "").replace("-", "")

    # Check if empty
    if not gtin:
        return ValidationResult(
            is_valid=False,
            identifier=original,
            errors=["GTIN cannot be empty"],
        )

    # Check if all digits
    if not gtin.isdigit():
        return ValidationResult(
            is_valid=False,
            identifier=original,
            normalized=gtin,
            errors=["GTIN must contain only digits"],
        )

    # Check length
    valid_lengths = {8, 12, 13, 14}
    if len(gtin) not in valid_lengths:
        return ValidationResult(
            is_valid=False,
            identifier=original,
            normalized=gtin,
            errors=[f"GTIN must be 8, 12, 13, or 14 digits (got {len(gtin)})"],
        )

    # Determine GTIN type
    gtin_type = GTINType(len(gtin))

    # Check if expected type matches
    if expected_type and gtin_type != expected_type:
        errors.append(
            f"Expected {expected_type.name} ({expected_type.value} digits), "
            f"got {gtin_type.name} ({gtin_type.value} digits)"
        )

    # Verify check digit
    if not verify_check_digit(gtin):
        expected_check = calculate_check_digit(gtin[:-1])
        errors.append(
            f"Invalid check digit. Expected '{expected_check}', got '{gtin[-1]}'"
        )

    # Additional validations based on type
    if gtin_type == GTINType.GTIN_8:
        # GTIN-8 should not have leading zeros except for the GS1-8 Prefix
        if gtin.startswith("0000"):
            warnings.append("GTIN-8 has excessive leading zeros")

    if gtin_type == GTINType.GTIN_14:
        # First digit is indicator digit (0-9)
        indicator = gtin[0]
        if indicator == "0":
            warnings.append(
                "Indicator digit 0 means this is a standard GTIN-13/12/8 "
                "expressed in GTIN-14 format"
            )

    # Check for all-zeros (invalid)
    if gtin == "0" * len(gtin):
        errors.append("GTIN cannot be all zeros")

    is_valid = len(errors) == 0

    return ValidationResult(
        is_valid=is_valid,
        identifier=original,
        identifier_type=gtin_type.name,
        normalized=gtin,
        check_digit=gtin[-1] if is_valid else calculate_check_digit(gtin[:-1]),
        errors=errors if errors else None,
        warnings=warnings if warnings else None,
    )


def validate_gtin8(gtin: str) -> ValidationResult:
    """Validate a GTIN-8 (EAN-8).

    GTIN-8 is used for very small products where a larger barcode won't fit.

    Args:
        gtin: 8-digit GTIN string

    Returns:
        ValidationResult
    """
    return validate_gtin(gtin, expected_type=GTINType.GTIN_8)


def validate_gtin12(gtin: str) -> ValidationResult:
    """Validate a GTIN-12 (UPC-A).

    GTIN-12 is primarily used in North America.

    Args:
        gtin: 12-digit GTIN string

    Returns:
        ValidationResult
    """
    return validate_gtin(gtin, expected_type=GTINType.GTIN_12)


def validate_gtin13(gtin: str) -> ValidationResult:
    """Validate a GTIN-13 (EAN-13).

    GTIN-13 is the most common format used worldwide.

    Args:
        gtin: 13-digit GTIN string

    Returns:
        ValidationResult
    """
    return validate_gtin(gtin, expected_type=GTINType.GTIN_13)


def validate_gtin14(gtin: str) -> ValidationResult:
    """Validate a GTIN-14 (ITF-14).

    GTIN-14 is used for trade items at various packaging levels.
    The first digit (indicator) specifies the packaging level (0-9).

    Args:
        gtin: 14-digit GTIN string

    Returns:
        ValidationResult
    """
    return validate_gtin(gtin, expected_type=GTINType.GTIN_14)


def normalize_gtin(gtin: str, target_length: int = 14) -> Optional[str]:
    """Normalize a GTIN to a specific length.

    Converts GTINs between formats by adding leading zeros.

    Args:
        gtin: Any valid GTIN (8, 12, 13, or 14 digits)
        target_length: Target length (default 14 for GTIN-14)

    Returns:
        Normalized GTIN string, or None if invalid

    Example:
        >>> normalize_gtin("4006381333931", 14)
        '04006381333931'
    """
    result = validate_gtin(gtin)
    if not result.is_valid:
        return None

    normalized = result.normalized

    if len(normalized) > target_length:
        return None

    return normalized.zfill(target_length)


def get_gtin_type(gtin: str) -> Optional[GTINType]:
    """Determine the type of a GTIN.

    Args:
        gtin: GTIN string to analyze

    Returns:
        GTINType enum value, or None if invalid
    """
    result = validate_gtin(gtin)
    if not result.is_valid:
        return None

    try:
        return GTINType(len(result.normalized))
    except ValueError:
        return None


def create_gtin(data_digits: str, length: int = 13) -> str:
    """Create a complete GTIN by calculating and appending the check digit.

    Args:
        data_digits: Digits without check digit
        length: Target GTIN length (8, 12, 13, or 14)

    Returns:
        Complete GTIN with check digit

    Raises:
        ValueError: If data_digits is invalid

    Example:
        >>> create_gtin("400638133393", 13)
        '4006381333931'
    """
    if length not in {8, 12, 13, 14}:
        raise ValueError(f"Invalid GTIN length: {length}. Must be 8, 12, 13, or 14")

    expected_data_length = length - 1

    # Clean input
    data = str(data_digits).strip().replace(" ", "").replace("-", "")

    if not data.isdigit():
        raise ValueError("Data digits must contain only numbers")

    # Pad with leading zeros if needed
    data = data.zfill(expected_data_length)

    if len(data) != expected_data_length:
        raise ValueError(
            f"Data digits for GTIN-{length} must be {expected_data_length} digits "
            f"(got {len(data)})"
        )

    check_digit = calculate_check_digit(data)
    return data + check_digit


# =============================================================================
# GLN Validation
# =============================================================================

def validate_gln(gln: str) -> ValidationResult:
    """Validate a GLN (Global Location Number).

    GLN is a 13-digit number used to identify parties and physical locations
    in the supply chain (warehouses, stores, factories, etc.).

    Structure: Company Prefix (variable) + Location Reference + Check Digit

    Args:
        gln: 13-digit GLN string

    Returns:
        ValidationResult with validation details

    Example:
        >>> result = validate_gln("5412345000013")
        >>> result.is_valid
        True
    """
    errors = []
    warnings = []

    # Normalize
    original = gln
    gln = str(gln).strip().replace(" ", "").replace("-", "")

    # Check if empty
    if not gln:
        return ValidationResult(
            is_valid=False,
            identifier=original,
            identifier_type="GLN",
            errors=["GLN cannot be empty"],
        )

    # Check if all digits
    if not gln.isdigit():
        return ValidationResult(
            is_valid=False,
            identifier=original,
            identifier_type="GLN",
            normalized=gln,
            errors=["GLN must contain only digits"],
        )

    # Check length (GLN is always 13 digits)
    if len(gln) != 13:
        return ValidationResult(
            is_valid=False,
            identifier=original,
            identifier_type="GLN",
            normalized=gln,
            errors=[f"GLN must be exactly 13 digits (got {len(gln)})"],
        )

    # Verify check digit
    if not verify_check_digit(gln):
        expected_check = calculate_check_digit(gln[:-1])
        errors.append(
            f"Invalid check digit. Expected '{expected_check}', got '{gln[-1]}'"
        )

    # Check for all-zeros (invalid)
    if gln == "0" * 13:
        errors.append("GLN cannot be all zeros")

    # Check GS1 prefix (first 3 digits)
    prefix = gln[:3]
    if prefix in ("000", "001", "002", "003", "004", "005", "006", "007", "008", "009"):
        warnings.append(
            f"GLN prefix {prefix} is reserved for internal use or specific applications"
        )

    is_valid = len(errors) == 0

    return ValidationResult(
        is_valid=is_valid,
        identifier=original,
        identifier_type="GLN",
        normalized=gln,
        check_digit=gln[-1] if is_valid else calculate_check_digit(gln[:-1]),
        errors=errors if errors else None,
        warnings=warnings if warnings else None,
    )


def create_gln(company_prefix: str, location_reference: str) -> str:
    """Create a complete GLN by calculating and appending the check digit.

    Args:
        company_prefix: GS1 company prefix (variable length)
        location_reference: Location reference number

    Returns:
        Complete 13-digit GLN with check digit

    Raises:
        ValueError: If inputs are invalid

    Example:
        >>> create_gln("5412345", "00001")
        '5412345000013'
    """
    # Clean inputs
    prefix = str(company_prefix).strip().replace(" ", "")
    location = str(location_reference).strip().replace(" ", "")

    if not prefix.isdigit():
        raise ValueError("Company prefix must contain only digits")
    if not location.isdigit():
        raise ValueError("Location reference must contain only digits")

    # Combine and pad to 12 digits
    data = prefix + location
    data = data.zfill(12)

    if len(data) != 12:
        raise ValueError(
            f"Company prefix + location reference must be exactly 12 digits "
            f"(got {len(prefix)} + {len(location)} = {len(prefix) + len(location)})"
        )

    check_digit = calculate_check_digit(data)
    return data + check_digit


# =============================================================================
# SSCC Validation
# =============================================================================

def validate_sscc(sscc: str) -> ValidationResult:
    """Validate an SSCC (Serial Shipping Container Code).

    SSCC is an 18-digit number used to identify individual logistics units
    (pallets, cases, parcels, etc.) in the supply chain.

    Structure:
    - Extension digit (1 digit): Additional identification
    - GS1 Company Prefix (variable): Assigned by GS1
    - Serial Reference (variable): Assigned by company
    - Check Digit (1 digit): Modulo-10 check digit

    Total length is always 18 digits.

    Args:
        sscc: 18-digit SSCC string

    Returns:
        ValidationResult with validation details

    Example:
        >>> result = validate_sscc("340123450000000018")
        >>> result.is_valid
        True
    """
    errors = []
    warnings = []

    # Normalize
    original = sscc
    sscc = str(sscc).strip().replace(" ", "").replace("-", "")

    # Remove any Application Identifier prefix
    if sscc.startswith("00"):
        sscc = sscc[2:]
        warnings.append("Removed AI (00) prefix from SSCC")

    # Check if empty
    if not sscc:
        return ValidationResult(
            is_valid=False,
            identifier=original,
            identifier_type="SSCC",
            errors=["SSCC cannot be empty"],
        )

    # Check if all digits
    if not sscc.isdigit():
        return ValidationResult(
            is_valid=False,
            identifier=original,
            identifier_type="SSCC",
            normalized=sscc,
            errors=["SSCC must contain only digits"],
        )

    # Check length (SSCC is always 18 digits)
    if len(sscc) != 18:
        return ValidationResult(
            is_valid=False,
            identifier=original,
            identifier_type="SSCC",
            normalized=sscc,
            errors=[f"SSCC must be exactly 18 digits (got {len(sscc)})"],
        )

    # Verify check digit
    if not verify_check_digit(sscc):
        expected_check = calculate_check_digit(sscc[:-1])
        errors.append(
            f"Invalid check digit. Expected '{expected_check}', got '{sscc[-1]}'"
        )

    # Check extension digit (first digit, can be 0-9)
    extension = sscc[0]
    if not extension.isdigit():
        errors.append("Extension digit must be 0-9")

    # Check for all-zeros (invalid)
    if sscc == "0" * 18:
        errors.append("SSCC cannot be all zeros")

    is_valid = len(errors) == 0

    return ValidationResult(
        is_valid=is_valid,
        identifier=original,
        identifier_type="SSCC",
        normalized=sscc,
        check_digit=sscc[-1] if is_valid else calculate_check_digit(sscc[:-1]),
        errors=errors if errors else None,
        warnings=warnings if warnings else None,
    )


def create_sscc(
    extension_digit: str,
    company_prefix: str,
    serial_reference: str
) -> str:
    """Create a complete SSCC by calculating and appending the check digit.

    Args:
        extension_digit: Single digit (0-9)
        company_prefix: GS1 company prefix
        serial_reference: Serial reference number

    Returns:
        Complete 18-digit SSCC with check digit

    Raises:
        ValueError: If inputs are invalid

    Example:
        >>> create_sscc("3", "4012345", "0000000001")
        '340123450000000018'
    """
    # Clean inputs
    ext = str(extension_digit).strip()
    prefix = str(company_prefix).strip().replace(" ", "")
    serial = str(serial_reference).strip().replace(" ", "")

    if len(ext) != 1 or not ext.isdigit():
        raise ValueError("Extension digit must be a single digit (0-9)")
    if not prefix.isdigit():
        raise ValueError("Company prefix must contain only digits")
    if not serial.isdigit():
        raise ValueError("Serial reference must contain only digits")

    # Combine to 17 digits
    data = ext + prefix + serial

    if len(data) < 17:
        # Pad serial reference to fill to 17 digits
        needed = 17 - len(ext) - len(prefix)
        serial = serial.zfill(needed)
        data = ext + prefix + serial

    if len(data) != 17:
        raise ValueError(
            f"Extension + company prefix + serial reference must be exactly 17 digits "
            f"(got {len(data)})"
        )

    check_digit = calculate_check_digit(data)
    return data + check_digit


# =============================================================================
# GSIN Validation (Global Shipment Identification Number)
# =============================================================================

def validate_gsin(gsin: str) -> ValidationResult:
    """Validate a GSIN (Global Shipment Identification Number).

    GSIN is a 17-digit number used to identify logical groupings of
    logistics units for shipment purposes.

    Args:
        gsin: 17-digit GSIN string

    Returns:
        ValidationResult with validation details
    """
    errors = []
    warnings = []

    # Normalize
    original = gsin
    gsin = str(gsin).strip().replace(" ", "").replace("-", "")

    # Remove Application Identifier if present
    if gsin.startswith("402"):
        gsin = gsin[3:]
        warnings.append("Removed AI (402) prefix from GSIN")

    if not gsin:
        return ValidationResult(
            is_valid=False,
            identifier=original,
            identifier_type="GSIN",
            errors=["GSIN cannot be empty"],
        )

    if not gsin.isdigit():
        return ValidationResult(
            is_valid=False,
            identifier=original,
            identifier_type="GSIN",
            normalized=gsin,
            errors=["GSIN must contain only digits"],
        )

    if len(gsin) != 17:
        return ValidationResult(
            is_valid=False,
            identifier=original,
            identifier_type="GSIN",
            normalized=gsin,
            errors=[f"GSIN must be exactly 17 digits (got {len(gsin)})"],
        )

    if not verify_check_digit(gsin):
        expected_check = calculate_check_digit(gsin[:-1])
        errors.append(
            f"Invalid check digit. Expected '{expected_check}', got '{gsin[-1]}'"
        )

    is_valid = len(errors) == 0

    return ValidationResult(
        is_valid=is_valid,
        identifier=original,
        identifier_type="GSIN",
        normalized=gsin,
        check_digit=gsin[-1] if is_valid else calculate_check_digit(gsin[:-1]),
        errors=errors if errors else None,
        warnings=warnings if warnings else None,
    )


# =============================================================================
# GS1 Prefix Validation
# =============================================================================

# GS1 Country Prefixes (first 3 digits of GTIN)
# Source: https://www.gs1.org/standards/id-keys/company-prefix
GS1_PREFIXES = {
    # UPC prefixes (US/Canada)
    ("000", "019"): "GS1 US",
    ("020", "029"): "In-store codes",
    ("030", "039"): "GS1 US (Drugs)",
    ("040", "049"): "GS1 US (Reserved)",
    ("050", "059"): "Coupons",
    ("060", "099"): "GS1 US",
    ("100", "139"): "GS1 US",

    # International prefixes
    ("300", "379"): "GS1 France",
    ("380", "380"): "GS1 Bulgaria",
    ("383", "383"): "GS1 Slovenia",
    ("385", "385"): "GS1 Croatia",
    ("387", "387"): "GS1 Bosnia-Herzegovina",
    ("389", "389"): "GS1 Montenegro",
    ("400", "440"): "GS1 Germany",
    ("450", "459"): "GS1 Japan",
    ("460", "469"): "GS1 Russia",
    ("470", "470"): "GS1 Kyrgyzstan",
    ("471", "471"): "GS1 Taiwan",
    ("474", "474"): "GS1 Estonia",
    ("475", "475"): "GS1 Latvia",
    ("476", "476"): "GS1 Azerbaijan",
    ("477", "477"): "GS1 Lithuania",
    ("478", "478"): "GS1 Uzbekistan",
    ("479", "479"): "GS1 Sri Lanka",
    ("480", "480"): "GS1 Philippines",
    ("481", "481"): "GS1 Belarus",
    ("482", "482"): "GS1 Ukraine",
    ("483", "483"): "GS1 Turkmenistan",
    ("484", "484"): "GS1 Moldova",
    ("485", "485"): "GS1 Armenia",
    ("486", "486"): "GS1 Georgia",
    ("487", "487"): "GS1 Kazakhstan",
    ("488", "488"): "GS1 Tajikistan",
    ("489", "489"): "GS1 Hong Kong",
    ("490", "499"): "GS1 Japan",
    ("500", "509"): "GS1 UK",
    ("520", "521"): "GS1 Greece",
    ("528", "528"): "GS1 Lebanon",
    ("529", "529"): "GS1 Cyprus",
    ("530", "530"): "GS1 Albania",
    ("531", "531"): "GS1 North Macedonia",
    ("535", "535"): "GS1 Malta",
    ("539", "539"): "GS1 Ireland",
    ("540", "549"): "GS1 Belgium & Luxembourg",
    ("560", "560"): "GS1 Portugal",
    ("569", "569"): "GS1 Iceland",
    ("570", "579"): "GS1 Denmark",
    ("590", "590"): "GS1 Poland",
    ("594", "594"): "GS1 Romania",
    ("599", "599"): "GS1 Hungary",
    ("600", "601"): "GS1 South Africa",
    ("603", "603"): "GS1 Ghana",
    ("604", "604"): "GS1 Senegal",
    ("608", "608"): "GS1 Bahrain",
    ("609", "609"): "GS1 Mauritius",
    ("611", "611"): "GS1 Morocco",
    ("613", "613"): "GS1 Algeria",
    ("615", "615"): "GS1 Nigeria",
    ("616", "616"): "GS1 Kenya",
    ("618", "618"): "GS1 Ivory Coast",
    ("619", "619"): "GS1 Tunisia",
    ("620", "620"): "GS1 Tanzania",
    ("621", "621"): "GS1 Syria",
    ("622", "622"): "GS1 Egypt",
    ("623", "623"): "GS1 Brunei",
    ("624", "624"): "GS1 Libya",
    ("625", "625"): "GS1 Jordan",
    ("626", "626"): "GS1 Iran",
    ("627", "627"): "GS1 Kuwait",
    ("628", "628"): "GS1 Saudi Arabia",
    ("629", "629"): "GS1 UAE",
    ("630", "630"): "GS1 Qatar",
    ("631", "631"): "GS1 Namibia",
    ("640", "649"): "GS1 Finland",
    ("690", "699"): "GS1 China",
    ("700", "709"): "GS1 Norway",
    ("729", "729"): "GS1 Israel",
    ("730", "739"): "GS1 Sweden",
    ("740", "740"): "GS1 Guatemala",
    ("741", "741"): "GS1 El Salvador",
    ("742", "742"): "GS1 Honduras",
    ("743", "743"): "GS1 Nicaragua",
    ("744", "744"): "GS1 Costa Rica",
    ("745", "745"): "GS1 Panama",
    ("746", "746"): "GS1 Dominican Republic",
    ("750", "750"): "GS1 Mexico",
    ("754", "755"): "GS1 Canada",
    ("759", "759"): "GS1 Venezuela",
    ("760", "769"): "GS1 Switzerland",
    ("770", "771"): "GS1 Colombia",
    ("773", "773"): "GS1 Uruguay",
    ("775", "775"): "GS1 Peru",
    ("777", "777"): "GS1 Bolivia",
    ("778", "779"): "GS1 Argentina",
    ("780", "780"): "GS1 Chile",
    ("784", "784"): "GS1 Paraguay",
    ("786", "786"): "GS1 Ecuador",
    ("789", "790"): "GS1 Brazil",
    ("800", "839"): "GS1 Italy",
    ("840", "849"): "GS1 Spain",
    ("850", "850"): "GS1 Cuba",
    ("858", "858"): "GS1 Slovakia",
    ("859", "859"): "GS1 Czech Republic",
    ("860", "860"): "GS1 Serbia",
    ("865", "865"): "GS1 Mongolia",
    ("867", "867"): "GS1 North Korea",
    ("868", "869"): "GS1 Turkey",
    ("870", "879"): "GS1 Netherlands",
    ("880", "880"): "GS1 South Korea",
    ("883", "883"): "GS1 Myanmar",
    ("884", "884"): "GS1 Cambodia",
    ("885", "885"): "GS1 Thailand",
    ("888", "888"): "GS1 Singapore",
    ("890", "890"): "GS1 India",
    ("893", "893"): "GS1 Vietnam",
    ("896", "896"): "GS1 Pakistan",
    ("899", "899"): "GS1 Indonesia",
    ("900", "919"): "GS1 Austria",
    ("930", "939"): "GS1 Australia",
    ("940", "949"): "GS1 New Zealand",
    ("950", "950"): "GS1 Global Office",
    ("951", "951"): "GS1 Global Office (EPCglobal)",
    ("955", "955"): "GS1 Malaysia",
    ("958", "958"): "GS1 Macau",
    ("960", "969"): "GS1 Global Office (GTIN-8)",
    ("977", "977"): "Serial publications (ISSN)",
    ("978", "979"): "Bookland (ISBN)",
    ("980", "980"): "Refund receipts",
    ("981", "984"): "Common Currency Coupons",
    ("990", "999"): "Coupons",
}


def get_gs1_prefix_info(identifier: str) -> Optional[Dict[str, str]]:
    """Get information about a GS1 prefix.

    Args:
        identifier: GTIN or other GS1 identifier

    Returns:
        Dict with prefix info, or None if not found

    Example:
        >>> get_gs1_prefix_info("8690123456789")
        {'prefix': '869', 'organization': 'GS1 Turkey', 'country': 'Turkey'}
    """
    # Normalize
    identifier = str(identifier).strip().replace(" ", "").replace("-", "")

    if len(identifier) < 3 or not identifier.isdigit():
        return None

    prefix_3 = identifier[:3]

    for (start, end), org in GS1_PREFIXES.items():
        if start <= prefix_3 <= end:
            # Extract country from org name if present
            country = None
            if org.startswith("GS1 "):
                country = org[4:]

            return {
                "prefix": prefix_3,
                "organization": org,
                "country": country,
            }

    return None


# =============================================================================
# Batch Validation
# =============================================================================

def validate_identifiers(
    identifiers: List[str],
    identifier_type: Optional[str] = None
) -> Dict[str, List[ValidationResult]]:
    """Validate multiple GS1 identifiers in batch.

    Args:
        identifiers: List of identifier strings to validate
        identifier_type: Optional type to validate all as ('gtin', 'gln', 'sscc')

    Returns:
        Dict with 'valid' and 'invalid' lists of ValidationResults
    """
    valid = []
    invalid = []

    for identifier in identifiers:
        if identifier_type == "gln":
            result = validate_gln(identifier)
        elif identifier_type == "sscc":
            result = validate_sscc(identifier)
        elif identifier_type == "gsin":
            result = validate_gsin(identifier)
        else:
            # Default to GTIN
            result = validate_gtin(identifier)

        if result.is_valid:
            valid.append(result)
        else:
            invalid.append(result)

    return {
        "valid": valid,
        "invalid": invalid,
        "total": len(identifiers),
        "valid_count": len(valid),
        "invalid_count": len(invalid),
    }


# =============================================================================
# Frappe Integration Helpers
# =============================================================================

def validate_product_gtin(product_doc) -> Optional[Dict[str, Any]]:
    """Validate GTIN from a Product Master document.

    This is designed to be used as a Frappe doc_events hook.

    Args:
        product_doc: Product Master document

    Returns:
        Dict with validation result, or None if no barcode
    """
    import frappe

    barcode = product_doc.get("barcode") or product_doc.get("gtin")
    if not barcode:
        return None

    result = validate_gtin(barcode)

    if not result.is_valid:
        # Log validation error
        frappe.log_error(
            message=f"GTIN validation failed for {product_doc.name}: {result.errors}",
            title="GS1 Validation Error"
        )

    return result.to_dict()


def validate_gtin_on_save(doc, method=None):
    """Hook function to validate GTIN when a document is saved.

    Can be used as a doc_events hook in hooks.py:

    doc_events = {
        "Product Master": {
            "validate": "frappe_pim.pim.utils.gs1_validation.validate_gtin_on_save"
        }
    }

    Args:
        doc: Document being saved
        method: Hook method name

    Raises:
        frappe.ValidationError: If GTIN is invalid
    """
    import frappe

    barcode = doc.get("barcode") or doc.get("gtin")
    if not barcode:
        return

    result = validate_gtin(barcode)

    if not result.is_valid:
        frappe.throw(
            f"Invalid GTIN: {', '.join(result.errors)}",
            title="GS1 Validation Error"
        )


def validate_gln_on_save(doc, method=None):
    """Hook function to validate GLN when a document is saved.

    Args:
        doc: Document being saved (e.g., Supplier, Customer, Warehouse)
        method: Hook method name

    Raises:
        frappe.ValidationError: If GLN is invalid
    """
    import frappe

    gln = doc.get("gln") or doc.get("global_location_number")
    if not gln:
        return

    result = validate_gln(gln)

    if not result.is_valid:
        frappe.throw(
            f"Invalid GLN: {', '.join(result.errors)}",
            title="GS1 Validation Error"
        )


# =============================================================================
# API Endpoints
# =============================================================================

def api_validate_gtin(gtin: str) -> Dict[str, Any]:
    """API endpoint for GTIN validation.

    Usage from JavaScript:
        frappe.call({
            method: 'frappe_pim.pim.utils.gs1_validation.api_validate_gtin',
            args: { gtin: '4006381333931' },
            callback: function(r) {
                console.log(r.message);
            }
        });

    Args:
        gtin: GTIN string to validate

    Returns:
        Dict with validation result
    """
    result = validate_gtin(gtin)
    response = result.to_dict()

    # Add prefix info if valid
    if result.is_valid:
        prefix_info = get_gs1_prefix_info(result.normalized)
        if prefix_info:
            response["prefix_info"] = prefix_info

    return response


def api_validate_gln(gln: str) -> Dict[str, Any]:
    """API endpoint for GLN validation.

    Args:
        gln: GLN string to validate

    Returns:
        Dict with validation result
    """
    result = validate_gln(gln)
    return result.to_dict()


def api_validate_sscc(sscc: str) -> Dict[str, Any]:
    """API endpoint for SSCC validation.

    Args:
        sscc: SSCC string to validate

    Returns:
        Dict with validation result
    """
    result = validate_sscc(sscc)
    return result.to_dict()


def api_calculate_check_digit(digits: str, identifier_type: str = "gtin13") -> Dict[str, Any]:
    """API endpoint for check digit calculation.

    Args:
        digits: Digits without check digit
        identifier_type: Type of identifier (gtin8, gtin12, gtin13, gtin14, gln, sscc)

    Returns:
        Dict with complete identifier
    """
    try:
        if identifier_type.lower() == "gln":
            # For GLN, pad to 12 digits
            data = digits.zfill(12)
            check_digit = calculate_check_digit(data)
            full_identifier = data + check_digit
        elif identifier_type.lower() == "sscc":
            # For SSCC, pad to 17 digits
            data = digits.zfill(17)
            check_digit = calculate_check_digit(data)
            full_identifier = data + check_digit
        else:
            # For GTIN, determine length from type
            length_map = {
                "gtin8": 8,
                "gtin12": 12,
                "gtin13": 13,
                "gtin14": 14,
            }
            length = length_map.get(identifier_type.lower(), 13)
            full_identifier = create_gtin(digits, length)

        return {
            "success": True,
            "input": digits,
            "identifier_type": identifier_type,
            "check_digit": full_identifier[-1],
            "full_identifier": full_identifier,
        }
    except ValueError as e:
        return {
            "success": False,
            "error": str(e),
        }


# =============================================================================
# Whitelisted Functions for Frappe API
# =============================================================================

# Functions to be whitelisted for external API calls
# Add to hooks.py: whitelist_methods = [...]
_WHITELISTED_METHODS = [
    "frappe_pim.pim.utils.gs1_validation.api_validate_gtin",
    "frappe_pim.pim.utils.gs1_validation.api_validate_gln",
    "frappe_pim.pim.utils.gs1_validation.api_validate_sscc",
    "frappe_pim.pim.utils.gs1_validation.api_calculate_check_digit",
]


def _wrap_for_whitelist():
    """Apply frappe.whitelist() decorator at runtime.

    This allows the module to be imported without frappe being available.
    """
    try:
        import frappe

        global api_validate_gtin, api_validate_gln, api_validate_sscc, api_calculate_check_digit

        api_validate_gtin = frappe.whitelist()(api_validate_gtin)
        api_validate_gln = frappe.whitelist()(api_validate_gln)
        api_validate_sscc = frappe.whitelist()(api_validate_sscc)
        api_calculate_check_digit = frappe.whitelist()(api_calculate_check_digit)
    except ImportError:
        pass


# Apply whitelist decorators when module is loaded in Frappe context
_wrap_for_whitelist()
