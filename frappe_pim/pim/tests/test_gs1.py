# Copyright (c) 2024, Frappe PIM and contributors
# For license information, please see license.txt
"""GS1 Validation Unit Tests

This module contains unit tests for:
- GTIN validation (GTIN-8, GTIN-12, GTIN-13, GTIN-14)
- GLN (Global Location Number) validation
- SSCC (Serial Shipping Container Code) validation
- GSIN (Global Shipment Identification Number) validation
- Check digit calculation
- GS1 prefix lookup
- Batch validation

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for linting/static analysis).
"""

import unittest


class TestCheckDigitCalculation(unittest.TestCase):
    """Test cases for GS1 check digit calculation algorithm."""

    def test_calculate_check_digit_gtin13(self):
        """Test check digit calculation for GTIN-13."""
        from frappe_pim.pim.utils.gs1_validation import calculate_check_digit

        # Known GTIN-13: 4006381333931 (check digit is 1)
        result = calculate_check_digit("400638133393")
        self.assertEqual(result, "1")

    def test_calculate_check_digit_gtin12(self):
        """Test check digit calculation for GTIN-12 (UPC-A)."""
        from frappe_pim.pim.utils.gs1_validation import calculate_check_digit

        # Known UPC-A: 012345678905 (check digit is 5)
        result = calculate_check_digit("01234567890")
        self.assertEqual(result, "5")

    def test_calculate_check_digit_gtin8(self):
        """Test check digit calculation for GTIN-8."""
        from frappe_pim.pim.utils.gs1_validation import calculate_check_digit

        # Known GTIN-8: 12345670 (check digit is 0)
        result = calculate_check_digit("1234567")
        self.assertEqual(result, "0")

    def test_calculate_check_digit_gtin14(self):
        """Test check digit calculation for GTIN-14."""
        from frappe_pim.pim.utils.gs1_validation import calculate_check_digit

        # Calculate for 13-digit data portion
        result = calculate_check_digit("1234567890123")
        self.assertIn(result, "0123456789")

    def test_calculate_check_digit_invalid_input(self):
        """Test check digit calculation with non-numeric input."""
        from frappe_pim.pim.utils.gs1_validation import calculate_check_digit

        with self.assertRaises(ValueError):
            calculate_check_digit("ABC123")

    def test_verify_check_digit_valid(self):
        """Test verify_check_digit with valid GTIN."""
        from frappe_pim.pim.utils.gs1_validation import verify_check_digit

        # Known valid GTIN-13
        self.assertTrue(verify_check_digit("4006381333931"))

    def test_verify_check_digit_invalid(self):
        """Test verify_check_digit with invalid check digit."""
        from frappe_pim.pim.utils.gs1_validation import verify_check_digit

        # Same GTIN but wrong check digit
        self.assertFalse(verify_check_digit("4006381333932"))

    def test_verify_check_digit_non_numeric(self):
        """Test verify_check_digit with non-numeric input."""
        from frappe_pim.pim.utils.gs1_validation import verify_check_digit

        self.assertFalse(verify_check_digit("ABC123DEF"))

    def test_verify_check_digit_too_short(self):
        """Test verify_check_digit with too short input."""
        from frappe_pim.pim.utils.gs1_validation import verify_check_digit

        self.assertFalse(verify_check_digit("1"))


class TestGTINValidation(unittest.TestCase):
    """Test cases for GTIN validation."""

    def test_validate_gtin13_valid(self):
        """Test validation of valid GTIN-13."""
        from frappe_pim.pim.utils.gs1_validation import validate_gtin

        result = validate_gtin("4006381333931")

        self.assertTrue(result.is_valid)
        self.assertEqual(result.identifier_type, "GTIN_13")
        self.assertEqual(result.normalized, "4006381333931")
        self.assertEqual(result.check_digit, "1")

    def test_validate_gtin12_valid(self):
        """Test validation of valid GTIN-12 (UPC-A)."""
        from frappe_pim.pim.utils.gs1_validation import validate_gtin

        result = validate_gtin("012345678905")

        self.assertTrue(result.is_valid)
        self.assertEqual(result.identifier_type, "GTIN_12")

    def test_validate_gtin8_valid(self):
        """Test validation of valid GTIN-8."""
        from frappe_pim.pim.utils.gs1_validation import validate_gtin

        result = validate_gtin("12345670")

        self.assertTrue(result.is_valid)
        self.assertEqual(result.identifier_type, "GTIN_8")

    def test_validate_gtin14_valid(self):
        """Test validation of valid GTIN-14."""
        from frappe_pim.pim.utils.gs1_validation import validate_gtin, create_gtin

        # Create a valid GTIN-14
        gtin14 = create_gtin("1234567890123", 14)
        result = validate_gtin(gtin14)

        self.assertTrue(result.is_valid)
        self.assertEqual(result.identifier_type, "GTIN_14")

    def test_validate_gtin_with_spaces(self):
        """Test validation normalizes spaces."""
        from frappe_pim.pim.utils.gs1_validation import validate_gtin

        result = validate_gtin("4006 3813 3393 1")

        self.assertTrue(result.is_valid)
        self.assertEqual(result.normalized, "4006381333931")

    def test_validate_gtin_with_dashes(self):
        """Test validation normalizes dashes."""
        from frappe_pim.pim.utils.gs1_validation import validate_gtin

        result = validate_gtin("4006-3813-3393-1")

        self.assertTrue(result.is_valid)
        self.assertEqual(result.normalized, "4006381333931")

    def test_validate_gtin_empty(self):
        """Test validation of empty GTIN."""
        from frappe_pim.pim.utils.gs1_validation import validate_gtin

        result = validate_gtin("")

        self.assertFalse(result.is_valid)
        self.assertIn("empty", result.errors[0].lower())

    def test_validate_gtin_non_numeric(self):
        """Test validation of non-numeric GTIN."""
        from frappe_pim.pim.utils.gs1_validation import validate_gtin

        result = validate_gtin("ABCD12345678")

        self.assertFalse(result.is_valid)
        self.assertIn("digits", result.errors[0].lower())

    def test_validate_gtin_wrong_length(self):
        """Test validation of GTIN with wrong length."""
        from frappe_pim.pim.utils.gs1_validation import validate_gtin

        result = validate_gtin("12345")

        self.assertFalse(result.is_valid)
        self.assertIn("8, 12, 13, or 14", result.errors[0])

    def test_validate_gtin_invalid_check_digit(self):
        """Test validation of GTIN with invalid check digit."""
        from frappe_pim.pim.utils.gs1_validation import validate_gtin

        result = validate_gtin("4006381333932")  # Wrong check digit

        self.assertFalse(result.is_valid)
        self.assertTrue(any("check digit" in e.lower() for e in result.errors))

    def test_validate_gtin_all_zeros(self):
        """Test validation of all-zero GTIN."""
        from frappe_pim.pim.utils.gs1_validation import validate_gtin

        result = validate_gtin("0000000000000")

        self.assertFalse(result.is_valid)
        self.assertTrue(any("all zeros" in e.lower() for e in result.errors))

    def test_validate_gtin_to_dict(self):
        """Test ValidationResult.to_dict method."""
        from frappe_pim.pim.utils.gs1_validation import validate_gtin

        result = validate_gtin("4006381333931")
        result_dict = result.to_dict()

        self.assertIsInstance(result_dict, dict)
        self.assertIn("is_valid", result_dict)
        self.assertIn("identifier", result_dict)
        self.assertIn("normalized", result_dict)


class TestGTINTypeValidation(unittest.TestCase):
    """Test cases for specific GTIN type validation."""

    def test_validate_gtin8(self):
        """Test validate_gtin8 function."""
        from frappe_pim.pim.utils.gs1_validation import validate_gtin8

        result = validate_gtin8("12345670")

        self.assertTrue(result.is_valid)
        self.assertEqual(result.identifier_type, "GTIN_8")

    def test_validate_gtin8_wrong_length(self):
        """Test validate_gtin8 with wrong length."""
        from frappe_pim.pim.utils.gs1_validation import validate_gtin8

        result = validate_gtin8("4006381333931")  # GTIN-13

        self.assertFalse(result.is_valid)
        self.assertTrue(any("GTIN_8" in e for e in result.errors))

    def test_validate_gtin12(self):
        """Test validate_gtin12 function."""
        from frappe_pim.pim.utils.gs1_validation import validate_gtin12

        result = validate_gtin12("012345678905")

        self.assertTrue(result.is_valid)
        self.assertEqual(result.identifier_type, "GTIN_12")

    def test_validate_gtin13(self):
        """Test validate_gtin13 function."""
        from frappe_pim.pim.utils.gs1_validation import validate_gtin13

        result = validate_gtin13("4006381333931")

        self.assertTrue(result.is_valid)
        self.assertEqual(result.identifier_type, "GTIN_13")

    def test_validate_gtin14(self):
        """Test validate_gtin14 function."""
        from frappe_pim.pim.utils.gs1_validation import validate_gtin14, create_gtin

        gtin14 = create_gtin("1234567890123", 14)
        result = validate_gtin14(gtin14)

        self.assertTrue(result.is_valid)
        self.assertEqual(result.identifier_type, "GTIN_14")


class TestGTINNormalization(unittest.TestCase):
    """Test cases for GTIN normalization."""

    def test_normalize_gtin_to_14(self):
        """Test normalizing GTIN-13 to GTIN-14."""
        from frappe_pim.pim.utils.gs1_validation import normalize_gtin

        result = normalize_gtin("4006381333931", 14)

        self.assertEqual(result, "04006381333931")

    def test_normalize_gtin_to_13(self):
        """Test normalizing GTIN-8 to GTIN-13."""
        from frappe_pim.pim.utils.gs1_validation import normalize_gtin

        result = normalize_gtin("12345670", 13)

        self.assertEqual(result, "0000012345670")

    def test_normalize_invalid_gtin(self):
        """Test normalizing invalid GTIN returns None."""
        from frappe_pim.pim.utils.gs1_validation import normalize_gtin

        result = normalize_gtin("invalid", 14)

        self.assertIsNone(result)

    def test_get_gtin_type(self):
        """Test getting GTIN type."""
        from frappe_pim.pim.utils.gs1_validation import get_gtin_type, GTINType

        result = get_gtin_type("4006381333931")

        self.assertEqual(result, GTINType.GTIN_13)


class TestCreateGTIN(unittest.TestCase):
    """Test cases for GTIN creation."""

    def test_create_gtin13(self):
        """Test creating GTIN-13 with check digit."""
        from frappe_pim.pim.utils.gs1_validation import create_gtin, verify_check_digit

        gtin = create_gtin("400638133393", 13)

        self.assertEqual(len(gtin), 13)
        self.assertTrue(verify_check_digit(gtin))

    def test_create_gtin12(self):
        """Test creating GTIN-12 with check digit."""
        from frappe_pim.pim.utils.gs1_validation import create_gtin, verify_check_digit

        gtin = create_gtin("01234567890", 12)

        self.assertEqual(len(gtin), 12)
        self.assertTrue(verify_check_digit(gtin))

    def test_create_gtin_with_padding(self):
        """Test creating GTIN with padding."""
        from frappe_pim.pim.utils.gs1_validation import create_gtin, verify_check_digit

        gtin = create_gtin("123456", 13)  # Short input

        self.assertEqual(len(gtin), 13)
        self.assertTrue(verify_check_digit(gtin))

    def test_create_gtin_invalid_length(self):
        """Test creating GTIN with invalid length."""
        from frappe_pim.pim.utils.gs1_validation import create_gtin

        with self.assertRaises(ValueError):
            create_gtin("123456789012", 15)  # Invalid length

    def test_create_gtin_non_numeric(self):
        """Test creating GTIN with non-numeric input."""
        from frappe_pim.pim.utils.gs1_validation import create_gtin

        with self.assertRaises(ValueError):
            create_gtin("ABC123", 13)


class TestGLNValidation(unittest.TestCase):
    """Test cases for GLN (Global Location Number) validation."""

    def test_validate_gln_valid(self):
        """Test validation of valid GLN."""
        from frappe_pim.pim.utils.gs1_validation import validate_gln, create_gln

        # Create a valid GLN
        gln = create_gln("5412345", "00001")
        result = validate_gln(gln)

        self.assertTrue(result.is_valid)
        self.assertEqual(result.identifier_type, "GLN")

    def test_validate_gln_wrong_length(self):
        """Test validation of GLN with wrong length."""
        from frappe_pim.pim.utils.gs1_validation import validate_gln

        result = validate_gln("123456789")  # Too short

        self.assertFalse(result.is_valid)
        self.assertTrue(any("13 digits" in e.lower() for e in result.errors))

    def test_validate_gln_invalid_check_digit(self):
        """Test validation of GLN with invalid check digit."""
        from frappe_pim.pim.utils.gs1_validation import validate_gln

        result = validate_gln("5412345000012")  # Wrong check digit

        self.assertFalse(result.is_valid)
        self.assertTrue(any("check digit" in e.lower() for e in result.errors))

    def test_validate_gln_non_numeric(self):
        """Test validation of GLN with non-numeric input."""
        from frappe_pim.pim.utils.gs1_validation import validate_gln

        result = validate_gln("541234500001A")

        self.assertFalse(result.is_valid)
        self.assertTrue(any("digits" in e.lower() for e in result.errors))

    def test_validate_gln_all_zeros(self):
        """Test validation of all-zero GLN."""
        from frappe_pim.pim.utils.gs1_validation import validate_gln

        result = validate_gln("0000000000000")

        self.assertFalse(result.is_valid)
        self.assertTrue(any("all zeros" in e.lower() for e in result.errors))

    def test_create_gln(self):
        """Test creating GLN with check digit."""
        from frappe_pim.pim.utils.gs1_validation import create_gln, verify_check_digit

        gln = create_gln("5412345", "00001")

        self.assertEqual(len(gln), 13)
        self.assertTrue(verify_check_digit(gln))

    def test_create_gln_invalid_prefix(self):
        """Test creating GLN with non-numeric prefix."""
        from frappe_pim.pim.utils.gs1_validation import create_gln

        with self.assertRaises(ValueError):
            create_gln("ABC1234", "00001")


class TestSSCCValidation(unittest.TestCase):
    """Test cases for SSCC (Serial Shipping Container Code) validation."""

    def test_validate_sscc_valid(self):
        """Test validation of valid SSCC."""
        from frappe_pim.pim.utils.gs1_validation import validate_sscc, create_sscc

        # Create a valid SSCC
        sscc = create_sscc("3", "4012345", "0000000001")
        result = validate_sscc(sscc)

        self.assertTrue(result.is_valid)
        self.assertEqual(result.identifier_type, "SSCC")

    def test_validate_sscc_wrong_length(self):
        """Test validation of SSCC with wrong length."""
        from frappe_pim.pim.utils.gs1_validation import validate_sscc

        result = validate_sscc("12345678901234567")  # 17 digits

        self.assertFalse(result.is_valid)
        self.assertTrue(any("18 digits" in e.lower() for e in result.errors))

    def test_validate_sscc_invalid_check_digit(self):
        """Test validation of SSCC with invalid check digit."""
        from frappe_pim.pim.utils.gs1_validation import validate_sscc, create_sscc

        # Create valid SSCC then change check digit
        sscc = create_sscc("3", "4012345", "0000000001")
        wrong_check = sscc[:-1] + ("0" if sscc[-1] != "0" else "1")
        result = validate_sscc(wrong_check)

        self.assertFalse(result.is_valid)
        self.assertTrue(any("check digit" in e.lower() for e in result.errors))

    def test_validate_sscc_with_ai_prefix(self):
        """Test validation of SSCC with Application Identifier prefix."""
        from frappe_pim.pim.utils.gs1_validation import validate_sscc, create_sscc

        sscc = create_sscc("3", "4012345", "0000000001")
        sscc_with_ai = "00" + sscc  # Add AI prefix

        result = validate_sscc(sscc_with_ai)

        self.assertTrue(result.is_valid)
        self.assertTrue(any("AI" in w for w in result.warnings or []))

    def test_create_sscc(self):
        """Test creating SSCC with check digit."""
        from frappe_pim.pim.utils.gs1_validation import create_sscc, verify_check_digit

        sscc = create_sscc("3", "4012345", "0000000001")

        self.assertEqual(len(sscc), 18)
        self.assertTrue(verify_check_digit(sscc))

    def test_create_sscc_invalid_extension(self):
        """Test creating SSCC with invalid extension digit."""
        from frappe_pim.pim.utils.gs1_validation import create_sscc

        with self.assertRaises(ValueError):
            create_sscc("AB", "4012345", "0000000001")


class TestGSINValidation(unittest.TestCase):
    """Test cases for GSIN (Global Shipment Identification Number) validation."""

    def test_validate_gsin_wrong_length(self):
        """Test validation of GSIN with wrong length."""
        from frappe_pim.pim.utils.gs1_validation import validate_gsin

        result = validate_gsin("1234567890123456")  # 16 digits

        self.assertFalse(result.is_valid)
        self.assertTrue(any("17 digits" in e.lower() for e in result.errors))

    def test_validate_gsin_non_numeric(self):
        """Test validation of GSIN with non-numeric input."""
        from frappe_pim.pim.utils.gs1_validation import validate_gsin

        result = validate_gsin("12345678901234ABC")

        self.assertFalse(result.is_valid)
        self.assertTrue(any("digits" in e.lower() for e in result.errors))


class TestGS1PrefixLookup(unittest.TestCase):
    """Test cases for GS1 prefix lookup."""

    def test_get_gs1_prefix_info_turkey(self):
        """Test GS1 prefix lookup for Turkey."""
        from frappe_pim.pim.utils.gs1_validation import get_gs1_prefix_info

        result = get_gs1_prefix_info("8690123456789")

        self.assertIsNotNone(result)
        self.assertEqual(result["prefix"], "869")
        self.assertIn("Turkey", result["organization"])

    def test_get_gs1_prefix_info_germany(self):
        """Test GS1 prefix lookup for Germany."""
        from frappe_pim.pim.utils.gs1_validation import get_gs1_prefix_info

        result = get_gs1_prefix_info("4006381333931")

        self.assertIsNotNone(result)
        self.assertEqual(result["prefix"], "400")
        self.assertIn("Germany", result["organization"])

    def test_get_gs1_prefix_info_us(self):
        """Test GS1 prefix lookup for US."""
        from frappe_pim.pim.utils.gs1_validation import get_gs1_prefix_info

        result = get_gs1_prefix_info("012345678905")

        self.assertIsNotNone(result)
        self.assertIn("GS1 US", result["organization"])

    def test_get_gs1_prefix_info_invalid(self):
        """Test GS1 prefix lookup with invalid input."""
        from frappe_pim.pim.utils.gs1_validation import get_gs1_prefix_info

        result = get_gs1_prefix_info("AB")

        self.assertIsNone(result)


class TestBatchValidation(unittest.TestCase):
    """Test cases for batch identifier validation."""

    def test_validate_identifiers_batch(self):
        """Test batch validation of multiple identifiers."""
        from frappe_pim.pim.utils.gs1_validation import validate_identifiers

        identifiers = [
            "4006381333931",  # Valid GTIN-13
            "012345678905",   # Valid GTIN-12
            "1234567890123",  # Invalid (wrong check digit)
        ]

        result = validate_identifiers(identifiers)

        self.assertEqual(result["total"], 3)
        self.assertEqual(result["valid_count"], 2)
        self.assertEqual(result["invalid_count"], 1)
        self.assertEqual(len(result["valid"]), 2)
        self.assertEqual(len(result["invalid"]), 1)

    def test_validate_identifiers_as_gln(self):
        """Test batch validation as GLN type."""
        from frappe_pim.pim.utils.gs1_validation import validate_identifiers, create_gln

        gln = create_gln("5412345", "00001")
        identifiers = [gln, "1234567890123"]

        result = validate_identifiers(identifiers, identifier_type="gln")

        self.assertEqual(result["valid_count"], 1)
        self.assertEqual(result["invalid_count"], 1)


class TestGTINTypeEnum(unittest.TestCase):
    """Test cases for GTINType enum."""

    def test_gtin_type_values(self):
        """Test GTINType enum values."""
        from frappe_pim.pim.utils.gs1_validation import GTINType

        self.assertEqual(GTINType.GTIN_8.value, 8)
        self.assertEqual(GTINType.GTIN_12.value, 12)
        self.assertEqual(GTINType.GTIN_13.value, 13)
        self.assertEqual(GTINType.GTIN_14.value, 14)


class TestGS1IdentifierTypeEnum(unittest.TestCase):
    """Test cases for GS1IdentifierType enum."""

    def test_gs1_identifier_type_values(self):
        """Test GS1IdentifierType enum values."""
        from frappe_pim.pim.utils.gs1_validation import GS1IdentifierType

        self.assertEqual(GS1IdentifierType.GTIN.value, "gtin")
        self.assertEqual(GS1IdentifierType.GLN.value, "gln")
        self.assertEqual(GS1IdentifierType.SSCC.value, "sscc")
        self.assertEqual(GS1IdentifierType.GSIN.value, "gsin")


class TestValidationResultDataClass(unittest.TestCase):
    """Test cases for ValidationResult data class."""

    def test_validation_result_creation(self):
        """Test creating ValidationResult."""
        from frappe_pim.pim.utils.gs1_validation import ValidationResult

        result = ValidationResult(
            is_valid=True,
            identifier="4006381333931",
            identifier_type="GTIN_13",
            normalized="4006381333931",
            check_digit="1"
        )

        self.assertTrue(result.is_valid)
        self.assertEqual(result.identifier, "4006381333931")
        self.assertEqual(result.identifier_type, "GTIN_13")

    def test_validation_result_with_errors(self):
        """Test ValidationResult with errors."""
        from frappe_pim.pim.utils.gs1_validation import ValidationResult

        result = ValidationResult(
            is_valid=False,
            identifier="invalid",
            errors=["Must contain only digits"],
            warnings=["Input was modified"]
        )

        self.assertFalse(result.is_valid)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(len(result.warnings), 1)

    def test_validation_result_to_dict(self):
        """Test ValidationResult.to_dict method."""
        from frappe_pim.pim.utils.gs1_validation import ValidationResult

        result = ValidationResult(
            is_valid=True,
            identifier="4006381333931",
            identifier_type="GTIN_13",
            normalized="4006381333931"
        )

        result_dict = result.to_dict()

        self.assertIsInstance(result_dict, dict)
        self.assertIn("is_valid", result_dict)
        self.assertIn("identifier", result_dict)
        self.assertIn("identifier_type", result_dict)
        self.assertIn("errors", result_dict)


class TestAPIEndpoints(unittest.TestCase):
    """Test cases for API endpoint functions."""

    def test_api_validate_gtin(self):
        """Test api_validate_gtin function."""
        from frappe_pim.pim.utils.gs1_validation import api_validate_gtin

        result = api_validate_gtin("4006381333931")

        self.assertIsInstance(result, dict)
        self.assertTrue(result["is_valid"])
        self.assertIn("prefix_info", result)

    def test_api_validate_gln(self):
        """Test api_validate_gln function."""
        from frappe_pim.pim.utils.gs1_validation import api_validate_gln, create_gln

        gln = create_gln("5412345", "00001")
        result = api_validate_gln(gln)

        self.assertIsInstance(result, dict)
        self.assertTrue(result["is_valid"])

    def test_api_validate_sscc(self):
        """Test api_validate_sscc function."""
        from frappe_pim.pim.utils.gs1_validation import api_validate_sscc, create_sscc

        sscc = create_sscc("3", "4012345", "0000000001")
        result = api_validate_sscc(sscc)

        self.assertIsInstance(result, dict)
        self.assertTrue(result["is_valid"])

    def test_api_calculate_check_digit_gtin13(self):
        """Test api_calculate_check_digit for GTIN-13."""
        from frappe_pim.pim.utils.gs1_validation import api_calculate_check_digit

        result = api_calculate_check_digit("400638133393", "gtin13")

        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"])
        self.assertEqual(result["check_digit"], "1")
        self.assertEqual(result["full_identifier"], "4006381333931")

    def test_api_calculate_check_digit_gln(self):
        """Test api_calculate_check_digit for GLN."""
        from frappe_pim.pim.utils.gs1_validation import api_calculate_check_digit

        result = api_calculate_check_digit("541234500001", "gln")

        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"])
        self.assertEqual(len(result["full_identifier"]), 13)

    def test_api_calculate_check_digit_invalid(self):
        """Test api_calculate_check_digit with invalid input."""
        from frappe_pim.pim.utils.gs1_validation import api_calculate_check_digit

        result = api_calculate_check_digit("ABC", "gtin13")

        self.assertIsInstance(result, dict)
        self.assertFalse(result["success"])
        self.assertIn("error", result)


# Allow module import without running tests
if __name__ == "__main__":
    unittest.main()
