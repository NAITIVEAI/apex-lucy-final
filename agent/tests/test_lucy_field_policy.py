import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from lucy_field_policy import (
    LUCY_AUTH_FIELDS,
    LUCY_CLASS_MEMBER_FORM_ID,
    LUCY_CLASS_MEMBER_FORM_TAB,
    LUCY_MEMBER_DISBURSEMENT_RELATIONSHIP,
    LUCY_MEMBER_DISBURSEMENT_SUBGRID_ID,
    LUCY_MEMBER_DISBURSEMENT_VIEW_ID,
    LUCY_MEMBER_DISBURSEMENT_VIEW_NAME,
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
        self.assertEqual(LUCY_MEMBER_DISBURSEMENT_SUBGRID_ID, "Lucy_Member_Disbursements")
        self.assertEqual(LUCY_MEMBER_DISBURSEMENT_VIEW_ID, "ec040b47-83c8-48d5-99f0-4bc80beba904")
        self.assertEqual(LUCY_MEMBER_DISBURSEMENT_VIEW_NAME, "Active Member Disbursements")
        self.assertEqual(
            LUCY_MEMBER_DISBURSEMENT_RELATIONSHIP,
            "new_new_classmember_new_memberdisbursement_ClassMember",
        )

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
        self.assertIn("cr7fe_classcountmetric", class_member_fields_for_outcome("all"))
        self.assertIn("cr7fe_pagacountmetric", class_member_fields_for_outcome("all"))
        self.assertIn("new_potentialclassmemberstatus", class_member_fields_for_outcome("all"))

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
                "cr7fe_classcountmetric",
                "new_pagaweeks",
                "cr7fe_pagacountmetric",
                "new_potentialclassmemberstatus",
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

        self.assertEqual(restricted, ("new_checkamount", "new_checkreissuerequest"))

    def test_disbursement_policy_uses_web_api_lookup_values_not_invalid_labels(self):
        fields = member_disbursement_fields(include_internal=True)

        self.assertIn("_new_classmember_value", fields)
        self.assertIn("_new_case_value", fields)
        self.assertIn("_new_disbursementdate_value", fields)
        self.assertIn("new_checkreissuerequest", fields)
        self.assertIn("new_checkreissuecompleted", fields)
        self.assertIn("_modifiedby_value", fields)
        self.assertNotIn("new_disbursementnumber", fields)
        self.assertNotIn("new_case", fields)
        self.assertNotIn("new_casedisbursement", fields)
        self.assertNotIn("modifiedby", fields)

    def test_filter_record_drops_out_of_policy_fields(self):
        record = {
            "new_apexid": "A123",
            "new_firstname": "Ada",
            "new_middlename": "Not Approved",
        }

        filtered = filter_record(record, class_member_fields_for_outcome("auth"))

        self.assertEqual(filtered, {"new_apexid": "A123", "new_firstname": "Ada"})

    def test_filter_record_keeps_formatted_values_for_allowed_lookup_fields(self):
        record = {
            "_new_case_value": "case-guid",
            "_new_case_value@OData.Community.Display.V1.FormattedValue": "Case Name",
            "new_disbursementnumber@OData.Community.Display.V1.FormattedValue": "Not allowed",
        }

        filtered = filter_record(record, {"_new_case_value"})

        self.assertEqual(
            filtered,
            {
                "_new_case_value": "case-guid",
                "_new_case_value@OData.Community.Display.V1.FormattedValue": "Case Name",
            },
        )


if __name__ == "__main__":
    unittest.main()
