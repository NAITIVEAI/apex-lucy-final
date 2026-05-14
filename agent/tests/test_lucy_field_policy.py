import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from lucy_field_policy import (
    LUCY_AUTH_FIELDS,
    LUCY_CLASS_MEMBER_FORM_ID,
    LUCY_CLASS_MEMBER_FORM_TAB,
    NOTICE_TEMPLATE_SCHEMA_MAP,
    class_member_fields_for_outcome,
    filter_record,
    member_disbursement_fields,
    restrict_fields,
)


class LucyFieldPolicyTests(unittest.TestCase):
    def test_policy_records_live_form_source(self):
        self.assertEqual(LUCY_CLASS_MEMBER_FORM_ID, "05e90c7f-deeb-4e50-b9c0-f7bf207bb3a2")
        self.assertEqual(LUCY_CLASS_MEMBER_FORM_TAB, "Lucy Class Member Data")

    def test_policy_includes_live_form_fields(self):
        class_member_schema_fields = {
            "new_apexid",
            "new_fullname",
            "new_firstname",
            "new_lastname",
            "new_shortsocial",
            "new_address",
            "new_city",
            "new_state",
            "new_zip",
            "new_email",
            "new_phonenumber",
            "new_pinnumber",
            "new_employeeid",
            "new_estimatedsettlementamount",
            "new_classworkweeks",
            "new_pagaweeks",
            "new_hiredate",
            "new_termdate",
            "new_rehiredate",
            "new_secondtermdate",
            "new_wagestatements",
            "new_totalearnings",
        }

        self.assertTrue(class_member_schema_fields.issubset(class_member_fields_for_outcome("all")))

    def test_notice_template_schema_map_uses_live_form_fields(self):
        mapped_fields = {
            mapping["d365_field"]
            for mapping in NOTICE_TEMPLATE_SCHEMA_MAP.values()
        }

        self.assertEqual(
            mapped_fields,
            {
                "new_estimatedsettlementamount",
                "new_classworkweeks",
                "new_pagaweeks",
            },
        )
        self.assertTrue(mapped_fields.issubset(class_member_fields_for_outcome("all")))

    def test_auth_outcome_is_limited_to_identity_fields(self):
        self.assertEqual(class_member_fields_for_outcome("auth"), LUCY_AUTH_FIELDS)
        self.assertNotIn("new_middlename", class_member_fields_for_outcome("auth"))
        self.assertNotIn("new_email", class_member_fields_for_outcome("auth"))

    def test_internal_ids_are_opt_in(self):
        fields = class_member_fields_for_outcome("settlement")
        with_internal = class_member_fields_for_outcome("settlement", include_internal=True)

        self.assertNotIn("new_classmemberid", fields)
        self.assertIn("new_classmemberid", with_internal)
        self.assertIn("new_estimatedsettlementamount", with_internal)

    def test_requested_disbursement_fields_are_restricted(self):
        restricted = restrict_fields(
            "new_checkamount,new_checkreissuerequest,new_name",
            member_disbursement_fields(include_internal=True),
        )

        self.assertEqual(restricted, ("new_checkamount",))

    def test_filter_record_drops_out_of_policy_fields(self):
        record = {
            "new_apexid": "A123",
            "new_firstname": "Ada",
            "new_middlename": "Not Approved",
        }

        filtered = filter_record(record, class_member_fields_for_outcome("auth"))

        self.assertEqual(filtered, {"new_apexid": "A123", "new_firstname": "Ada"})


if __name__ == "__main__":
    unittest.main()
