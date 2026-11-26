# Business rules

Every business rule of the app and of the site, the code that keeps it and the
test that proves it. The Desk page **Business Rules** (`/app/business-rules`)
shows these in plain words, to System Managers only.

How to keep it true:

- A new rule takes the next free number of its group. A number is never used
  again, even after the rule is dropped.
- A change to a rule changes its row here in the same commit, and its plain
  words in [plain.json](plain.json). `test_rules_policy` fails until both
  follow, and says which `source` to write.
- **Home** names the code that keeps the rule, as `file::name` under
  `custom_app/`. Everything in `hooks.py` is the home of a rule.
- **Test** names each test as `file::test`.
  `seen on the site` says the rule was set up in the Desk and when it was read
  there. The page shows the site as it is now.
- Examples are made up. No person, email, PAN, GSTIN or key goes in this file.

Run the tests without a site, with Frappe, ERPNext and HRMS on the Python path:

```bash
python -m unittest custom_app.tests.test_rules_policy custom_app.tests.test_rules_page \
    custom_app.tests.test_rules_purchase custom_app.tests.test_rules_budget \
    custom_app.tests.test_rules_people custom_app.tests.test_rules_access \
    custom_app.tests.test_rules_eoms
```

Or on a bench, one module at a time, as for `test_budget_integration`:

```bash
bench --site <site> run-tests --skip-before-tests --module custom_app.tests.test_rules_policy
```


## BC Budget check on purchase requests

| ID | Rule | Home | Test |
| --- | --- | --- | --- |
| BC-01 | With Use Transaction Date for PR Budget Check on, a purchase request uses the budget of the month and fiscal year of its Transaction Date, in the app's check and in ERPNext's own | `api/budget_control.py::get_other_condition`, `api/budget_control.py::patch_core_budget`, `overrides/material_request.py::CustomMaterialRequest`, `overrides/material_request.py::validate_budget` | test_budget_integration::test_a1_custom_check_uses_transaction_month_not_required_by, test_budget_integration::test_a1_core_check_uses_transaction_month_when_toggle_on, test_budget_integration::test_a3_march_pr_required_in_april_counts_in_current_fiscal_year |
| BC-02 | With that setting off, ERPNext's own check uses the Required By date | `overrides/material_request.py::validate_budget` | test_budget_integration::test_a2_core_check_uses_required_by_month_when_toggle_off |
| BC-03 | With Restrict PR to Current Month Budget on, a request may use at most its own month's budget less what the month has used. Unused budget of earlier months does not count | `api/budget_control.py::validate_material_request`, `api/budget_control.py::validate_current_month_budget` | test_budget_integration::test_b1_pr_below_month_left_is_allowed, test_budget_integration::test_b2_pr_equal_to_left_allowed_then_one_rupee_more_blocked, test_budget_integration::test_b3_unused_september_budget_does_not_help_october, test_budget_integration::test_b5_month_with_zero_allocation_blocks_any_pr, test_rules_budget::test_what_the_month_already_used_is_taken_off_first, test_rules_budget::test_each_check_runs_only_when_its_setting_is_on |
| BC-04 | With that setting off, ERPNext's accumulated monthly budget applies, so unused earlier months count | `api/budget_control.py::validate_material_request` | test_budget_integration::test_b4_without_month_restriction_accumulated_budget_applies |
| BC-05 | A month's budget is the annual amount times the month's share in the Monthly Distribution, or one twelfth when the Budget has no distribution | `api/budget_control.py::get_month_budget` | test_rules_budget::test_a_months_budget_is_its_share_of_the_year, test_rules_budget::test_without_a_distribution_a_month_gets_one_twelfth |
| BC-06 | An account and cost center with no submitted Budget applicable on Material Request is not checked by the month rule | `api/budget_control.py::get_month_budget`, `api/budget_control.py::validate_current_month_budget` | test_rules_budget::test_an_account_with_no_budget_for_requests_is_not_checked |
| BC-07 | Rows of one request on the same account and cost center are added up before the check | `api/budget_control.py::validate_current_month_budget` | test_rules_budget::test_rows_on_one_account_and_cost_center_are_checked_together |
| BC-08 | Only requests of type Purchase use the month's budget | `api/budget_control.py::validate_current_month_budget` | test_rules_budget::test_only_purchase_requests_use_the_months_budget |
| BC-09 | A submitted request counts in full and only once, through its quotation, order, receipt, invoice and payment | `api/budget_control.py::get_month_consumption`, `api/budget_control.py::get_monthly_consumption` | test_budget_integration::test_d1_submitted_pr_nothing_ordered_counts_in_full, test_budget_integration::test_d2_d3_pr_po_receipt_invoice_payment_counts_once, test_budget_integration::test_k1_pr_quotation_po_invoice_payment_counts_once |
| BC-10 | A Stopped request counts only for the part already ordered | `api/budget_control.py::PR_CONSUMED_AMOUNT` | test_budget_integration::test_d4_stopped_pr_nothing_ordered_counts_zero, test_budget_integration::test_d5_stopped_pr_half_ordered_counts_half |
| BC-11 | A cancelled or rejected request counts nothing. When its order is cancelled, the request is open again and still counts | `api/budget_control.py::get_month_consumption` | test_budget_integration::test_d7_cancelled_pr_counts_zero, test_budget_integration::test_k7_rejected_pr_counts_zero, test_budget_integration::test_k5_cancelled_po_reopens_pr_and_pr_still_counts |
| BC-12 | A submitted expense claim counts at its sanctioned amount in the month of its posting date. A draft, rejected or finance rejected claim counts nothing | `api/budget_control.py::get_month_consumption` | test_budget_integration::test_d6_approved_claim_counts_at_sanctioned_amount, test_budget_integration::test_d6_rejected_claim_counts_zero, test_budget_integration::test_d6_draft_claim_counts_zero, test_budget_integration::test_d6_finance_rejected_claim_counts_zero |
| BC-13 | A Journal Entry's rows on the account and cost center count at debit less credit in the month of its posting date. Cancelled and opening entries do not count | `api/budget_control.py::JOURNAL_ENTRY_CONDITIONS` | test_budget_integration::test_d8_journal_entry_counts_as_used, test_budget_integration::test_d8_correcting_journal_entry_is_not_counted_twice, test_budget_integration::test_d8_cancelled_journal_entry_counts_zero, test_budget_integration::test_d8_journal_entry_counts_in_its_posting_month |
| BC-14 | With Restrict Backdated PR on, a Transaction Date before today is refused when it is set or changed. A draft raised earlier can still be approved | `api/budget_control.py::validate_backdated_pr`, `api/budget_control.py::get_pr_restrictions`, `public/js/material_request.js` | test_budget_integration::test_c1_pr_dated_previous_month_is_blocked, test_budget_integration::test_c1b_pr_dated_yesterday_is_blocked_rule_is_before_today, test_budget_integration::test_c2_pr_dated_today_is_allowed, test_budget_integration::test_c3_toggle_off_allows_previous_month, test_rules_budget::test_a_draft_raised_earlier_can_still_be_approved, test_rules_budget::test_a_date_moved_into_the_past_is_refused |
| BC-15 | Requests raised before the effective date of the transaction date setting are counted in their Required By month. The date matters only while the setting is on | `api/budget_control.py::get_pr_date_basis` | test_rules_budget::test_requests_before_the_effective_date_keep_their_required_by_month, test_rules_budget::test_the_effective_date_counts_only_while_the_setting_is_on |
| BC-16 | A fiscal year's months run from its first month to its last | `api/budget_control.py::get_fiscal_year_months` | test_rules_budget::test_a_years_months_run_from_april_to_march |
| BC-17 | The checks work on ERPNext before and from 15.125, and in a worker that has loaded nothing else yet | `__init__.py::_apply_patches`, `api/budget_control.py::core_uses_query_builder_conditions`, `overrides/budget.py::apply_budget_patch` | test_budget_integration::test_old_signature_uses_transaction_date_when_toggle_on, test_budget_integration::test_h3_first_budget_check_in_fresh_worker, test_rules_budget::test_the_requested_amount_fix_is_only_for_older_erpnext |
| BC-18 | On ERPNext before 15.125, the amount requested and not yet ordered is summed row by row, each at its own rate | `overrides/budget.py::get_requested_amount_fixed` | test_rules_budget::test_the_requested_amount_is_summed_row_by_row |
| BC-19 | A Journal Entry over the accumulated budget is refused by ERPNext's own check. With every app setting off, requests are checked as in standard ERPNext | `api/budget_control.py::validate_material_request` | test_budget_integration::test_h1_journal_entry_over_accumulated_budget_is_blocked, test_budget_integration::test_h2_all_toggles_off_pr_behaves_like_standard_erpnext |

## BU Budgets and the Master Budget

| ID | Rule | Home | Test |
| --- | --- | --- | --- |
| BU-01 | A department appears once in a Master Budget | `custom_app/doctype/master_budget/master_budget.py::validate_duplicate_departments` | test_rules_budget::test_a_department_is_listed_once |
| BU-02 | The departments of a Master Budget together do not exceed its total | `custom_app/doctype/master_budget/master_budget.py::validate_budget_total` | test_budget_integration::test_g1_cost_center_rows_cannot_exceed_master_total, test_rules_budget::test_departments_together_stay_within_the_total |
| BU-03 | On submit, a Budget and the other submitted Budgets of its cost center and year stay within the cost center's Master Budget row. A cost center with no row is not checked, and the Budget being amended is not counted twice | `overrides/budget.py::validate_master_budget_limit` | test_budget_integration::test_g1_budget_saved_directly_over_master_is_blocked, test_budget_integration::test_g1_budget_saved_directly_within_master_is_allowed, test_budget_integration::test_g1_cost_center_without_master_row_is_not_checked, test_budget_integration::test_g1_amending_a_budget_does_not_count_it_twice |
| BU-04 | A Master Budget amended with a higher total applies at once | `custom_app/doctype/master_budget/master_budget.py::MasterBudget` | test_budget_integration::test_g2_amended_master_budget_with_higher_total_applies |

## BR Changing budgets

| ID | Rule | Home | Test |
| --- | --- | --- | --- |
| BR-01 | A draft Budget Reallocation changes no budget | `custom_app/doctype/budget_reallocation/budget_reallocation.py::on_submit` | test_budget_integration::test_f1_draft_changes_no_budget |
| BR-02 | Approving a reallocation amends the Budget and its monthly split. The other eleven months keep their amounts, and the request check and the report use the new amount at once | `custom_app/doctype/budget_reallocation/budget_reallocation.py::reallocate_budget`, `custom_app/doctype/budget_reallocation/budget_reallocation.py::update_monthly_distribution`, `custom_app/doctype/budget_reallocation/budget_reallocation.py::cancel_and_amend_budget` | test_budget_integration::test_f2_approve_amends_budget_and_keeps_other_months, test_budget_integration::test_f5_pr_check_and_report_use_new_month_amount_at_once |
| BR-03 | A reallocation starts from the month's present budget and shows the difference and the new annual total | `custom_app/doctype/budget_reallocation/budget_reallocation.py::calculate_current_budget`, `custom_app/doctype/budget_reallocation/budget_reallocation.py::calculate_differences` | test_rules_budget::test_it_starts_from_the_months_present_budget |
| BR-04 | A reallocation needs a Monthly Distribution and a submitted Budget for the account, and a reason | `custom_app/doctype/budget_reallocation/budget_reallocation.py::calculate_current_budget`, `custom_app/doctype/budget_reallocation/budget_reallocation.json` | test_rules_budget::test_it_needs_a_monthly_distribution, test_rules_budget::test_it_needs_a_submitted_budget_for_the_account, test_rules_budget::test_it_needs_a_reason_and_a_new_amount |
| BR-05 | A month cannot be reduced below what it has used: requests, claims and Journal Entries. With the month restriction off, the budget up to the month is compared with the use up to the month. A Stopped request does not block a reduction | `custom_app/doctype/budget_reallocation/budget_reallocation.py::validate_material_requests`, `custom_app/doctype/budget_reallocation/budget_reallocation.py::get_total_budget_till_month` | test_budget_integration::test_f3_cannot_reduce_month_below_what_it_already_used, test_budget_integration::test_f3_expense_claims_count_as_used, test_budget_integration::test_f3_journal_entries_count_as_used, test_budget_integration::test_f3_without_month_restriction_budget_to_date_is_checked, test_budget_integration::test_f3_stopped_pr_does_not_block_a_reduction |
| BR-06 | An increase needs room in the cost center's Master Budget row | `custom_app/doctype/budget_reallocation/budget_reallocation.py::validate_budget_limit`, `custom_app/doctype/budget_reallocation/budget_reallocation.py::get_master_budget_limit` | test_budget_integration::test_f4_increase_needs_master_budget_headroom, test_rules_budget::test_an_increase_beyond_the_master_budget_is_refused |
| BR-07 | The old and new Budget, the approver and the time are recorded on the reallocation | `custom_app/doctype/budget_reallocation/budget_reallocation.py::cancel_and_amend_budget` | test_budget_integration::test_f6_named_approver_is_recorded |
| BR-08 | Budget Upload makes one monthly split and one Budget per account, with the exact months of the file | `custom_app/doctype/budget_upload/budget_upload.py::create_monthly_distributions` | test_budget_integration::test_i1_upload_creates_budget_with_exact_months |
| BR-09 | An upload is refused when it goes over the Master Budget, or when the cost center has no row in it | `custom_app/doctype/budget_upload/budget_upload.py::get_master_budget_limit`, `custom_app/doctype/budget_upload/budget_upload.py::get_allocated_budget` | test_budget_integration::test_i2_upload_over_master_budget_is_blocked, test_budget_integration::test_i3_upload_for_cost_center_missing_from_master_is_blocked |
| BR-10 | Rows whose account already has a Budget or does not exist are skipped and add nothing to the Master Budget check | `custom_app/doctype/budget_upload/budget_upload.py::account_has_budget` | test_budget_integration::test_i4_reupload_with_existing_account_counts_only_new_rows, test_budget_integration::test_i4_unknown_account_row_adds_nothing_to_master_check |
| BR-11 | The upload preview marks every cell that is not a number | `custom_app/doctype/budget_upload/budget_upload.py::get_excel_preview` | test_rules_budget::test_the_preview_marks_cells_that_are_not_numbers |
| BR-12 | A mid year file is compared with the submitted Budgets month by month. A month that moves by a rupee or more is changed, the rest is left alone, and a file that changes nothing is refused | `custom_app/doctype/mid_year_budget_upload/mid_year_budget_upload.py::compare`, `custom_app/doctype/mid_year_budget_upload/mid_year_budget_upload.py::before_submit` | test_budget_integration::test_j1_revised_month_amends_budget_others_unchanged, test_budget_integration::test_j2_unchanged_file_is_refused, test_rules_budget::test_a_month_moved_by_less_than_a_rupee_is_unchanged |
| BR-13 | Reductions are applied before increases, so budget moves between accounts with no room in the Master Budget | `custom_app/doctype/mid_year_budget_upload/mid_year_budget_upload.py::apply` | test_budget_integration::test_j1_moving_budget_between_accounts_with_no_headroom |
| BR-14 | A month cut below what it has used is applied with a warning, and what is left goes negative | `custom_app/doctype/mid_year_budget_upload/mid_year_budget_upload.py::compare` | test_budget_integration::test_j3_cut_below_consumed_applies_with_warning_and_left_goes_negative |
| BR-15 | A mid year file over the Master Budget, with months out of order, repeated accounts, or amounts that are negative or not numbers is refused | `custom_app/doctype/mid_year_budget_upload/mid_year_budget_upload.py::read_file`, `custom_app/doctype/mid_year_budget_upload/mid_year_budget_upload.py::validate_master_budget` | test_budget_integration::test_j4_over_master_budget_is_refused, test_budget_integration::test_j5_months_out_of_order_are_refused, test_rules_budget::test_repeated_accounts_and_bad_amounts_are_refused, test_rules_budget::test_the_spreadsheets_months_are_april_to_march |
| BR-16 | An account in a mid year file must exist, belong to the company and not be a group. The cost center must belong to the company | `custom_app/doctype/mid_year_budget_upload/mid_year_budget_upload.py::validate_accounts`, `custom_app/doctype/mid_year_budget_upload/mid_year_budget_upload.py::validate` | test_rules_budget::test_accounts_must_be_in_the_company_and_not_groups, test_rules_budget::test_the_cost_center_must_belong_to_the_company |
| BR-17 | A blank row never removes a budget. An account with no Budget yet gets one, which stops requests, orders and actual expenses over budget | `custom_app/doctype/mid_year_budget_upload/mid_year_budget_upload.py::compare`, `custom_app/doctype/mid_year_budget_upload/mid_year_budget_upload.py::create_budget`, `custom_app/doctype/mid_year_budget_upload/mid_year_budget_upload.py::NEW_BUDGET_CONTROLS` | test_budget_integration::test_j6_new_account_gets_a_budget, test_rules_budget::test_a_blank_row_never_removes_a_budget, test_rules_budget::test_new_budgets_stop_on_requests_orders_and_actuals |
| BR-18 | A Budget that holds several accounts is not revised from a file | `custom_app/doctype/mid_year_budget_upload/mid_year_budget_upload.py::compare` | test_rules_budget::test_a_budget_of_several_accounts_is_not_revised_from_a_file |
| BR-19 | A Mid Year Budget Upload cannot be cancelled | `custom_app/doctype/mid_year_budget_upload/mid_year_budget_upload.py::before_cancel` | test_budget_integration::test_j7_upload_cannot_be_cancelled |

## RP Budget reports

| ID | Rule | Home | Test |
| --- | --- | --- | --- |
| RP-01 | The Budget Availability Report shows each month's budget, use and what is left. Left is exactly what a request can still use, with nothing from other cost centers | `custom_app/report/budget_availability_report/budget_availability_report.py::get_data` | test_budget_integration::test_e1_month_budgets_follow_distribution_and_add_up, test_budget_integration::test_e4_report_left_is_exactly_what_a_pr_can_use, test_budget_integration::test_e5_other_cost_center_does_not_leak |
| RP-02 | Overspending in earlier months lowers Left in later months, and the request check agrees | `custom_app/report/budget_availability_report/budget_availability_report.py::get_data` | test_budget_integration::test_e3_overspent_earlier_month_caps_left_and_pr_check_agrees |
| RP-03 | On a site with live data, the report's figures match figures worked out by hand | `custom_app/report/budget_availability_report/budget_availability_report.py::get_data` | test_budget_integration::test_m1_lib_002_left_matches_hand_worked_figures, test_budget_integration::test_m2_stopped_lib_002_prs_count_nothing |
| RP-04 | The Carry Forward Report adds what each month left, or takes off what it overspent, to the next. It stops at the present month, and shows a past year in full | `custom_app/report/budget_carry_forward_report/budget_carry_forward_report.py::get_data`, `custom_app/report/budget_carry_forward_report/budget_carry_forward_report.py::get_months_in_fiscal_year` | test_rules_budget::test_carry_forward_rolls_on_what_is_left_and_what_is_overspent, test_rules_budget::test_carry_forward_stops_at_the_present_month |
| RP-05 | The Committed against Actual Report counts as actual the finance approved claims and the submitted invoices. Its raised column counts every submitted request in full, also a Stopped one, so it can be higher than the use in the Budget Availability Report | `custom_app/report/budget_committed_actual_report/budget_committed_actual_report.py::get_actual_amount`, `custom_app/report/budget_committed_actual_report/budget_committed_actual_report.py::get_material_request_amount` | - |
| RP-06 | The Version History Report walks back from a Budget through its reallocations and mid year uploads to the first one | `custom_app/report/budget_version_history_report/budget_version_history_report.py::execute` | test_rules_budget::test_version_history_walks_back_to_the_first_budget |
| RP-07 | The Institution Budget Report shows only the cost center of the user's own department | `custom_app/report/institution_budget_report/institution_budget_report.py::execute` | test_rules_budget::test_institution_budget_shows_only_the_users_own_department |
| RP-08 | The User Role Report shows which user holds which role, leaving out internal roles | `custom_app/report/user_role_report/user_role_report.py::execute` | test_rules_budget::test_the_user_role_report_shows_who_holds_which_role |
| RP-09 | The Payment Register lists Payment Entries for the accounts, AP, audit and finance approver roles | `custom_app/report/payment_register_report/payment_register_report.json` | - |

## PR Purchase requests

| ID | Rule | Home | Test |
| --- | --- | --- | --- |
| PR-01 | A request must name the employee, the cost center, the approver and notes, and a rate on each row | `custom_app/custom/material_request.json`, `custom_app/custom/material_request_item.json` | test_rules_purchase::test_a_request_must_name_employee_cost_center_approver_and_notes |
| PR-02 | Every row takes the cost center of the request | `api/material_request.py::update_item_cost_center` | test_rules_purchase::test_every_row_takes_the_requests_cost_center |
| PR-03 | The employee must have a department, and that department a cost center | `api/material_request.py::update_item_cost_center` | test_rules_purchase::test_an_employee_without_a_department_cannot_raise_a_request, test_rules_purchase::test_a_department_without_a_cost_center_cannot_raise_a_request |
| PR-04 | An active fiscal year must cover the request's date | `api/material_request.py::update_item_cost_center` | test_rules_purchase::test_a_request_needs_an_active_fiscal_year_on_its_date |
| PR-05 | Each item must have a default expense account in the company | `api/material_request.py::update_item_cost_center`, `custom_app/custom/item_default.json` | test_rules_purchase::test_an_item_needs_an_expense_account_in_the_company |
| PR-06 | A submitted Budget must exist for the item's account, the cost center, the company and the year | `api/material_request.py::update_item_cost_center` | test_rules_purchase::test_a_request_needs_a_submitted_budget_on_its_account_and_cost_center |
| PR-07 | On every save, each row's expense account is taken again from its item, then item group, brand and company. A row with no account anywhere keeps its own | `overrides/material_request.py::sync_expense_account`, `overrides/material_request.py::_expected_expense_account` | test_rules_purchase::test_the_expense_account_follows_the_item_on_every_save, test_rules_purchase::test_an_item_with_no_account_anywhere_keeps_the_rows_own, test_rules_purchase::test_the_account_comes_from_item_then_group_then_brand_then_company |
| PR-08 | Rates typed on a new request are kept. They change later only with the price list | `overrides/material_request.py::update_item_rates` | test_rules_purchase::test_rates_typed_on_a_new_request_are_kept |
| PR-09 | A cost center listed in Verifier PR Settings needs a verifier. On any other the verifier is cleared | `api/material_request.py::validate_request_verifier`, `public/js/material_request.js` | test_rules_purchase::test_a_listed_cost_center_needs_a_verifier, test_rules_purchase::test_a_cost_center_that_is_not_listed_has_no_verifier |
| PR-10 | A new request emails its approver. With no approver, no one is emailed | `api/material_request.py::notify_approver_on_create` | test_budget_integration::test_k10_new_pr_notifies_its_approver, test_rules_purchase::test_a_new_request_emails_its_approver, test_rules_purchase::test_a_request_with_no_approver_emails_no_one |
| PR-11 | The employee is emailed once when the request is rejected | `api/material_request.py::notify_employee_on_status_change` | test_rules_purchase::test_the_employee_is_told_when_a_request_is_rejected, test_rules_purchase::test_saving_a_rejected_request_again_sends_no_second_email |
| PR-12 | Every day, a submitted purchase request that is thirty days old with nothing ordered is cancelled, its workflow state set to Cancelled and its employee emailed. Stopped, ordered and partly ordered requests and other types are left alone | `tasks/auto_cancel_material_request.py::cancel_unordered_material_requests`, `tasks/auto_cancel_material_request.py::set_cancelled_workflow_state`, `tasks/auto_cancel_material_request.py::notify_requester` | test_budget_integration::test_auto_cancel_releases_budget_after_30_days, test_budget_integration::test_auto_cancel_leaves_ordered_pr_alone, test_rules_purchase::test_a_request_with_no_order_is_cancelled_after_thirty_days, test_rules_purchase::test_stopped_ordered_and_non_purchase_requests_are_left_alone |
| PR-13 | A request with a submitted order is left alone. A draft order is kept and gets a comment that says why | `tasks/auto_cancel_material_request.py::get_linked_purchase_orders`, `tasks/auto_cancel_material_request.py::comment_on_purchase_order` | test_rules_purchase::test_a_request_with_a_submitted_order_is_left_alone, test_rules_purchase::test_a_draft_order_is_kept_with_a_comment |
| PR-14 | A dry run of the cancel changes nothing, and one request that fails does not stop the others | `tasks/auto_cancel_material_request.py::cancel_unordered_material_requests` | test_rules_purchase::test_a_dry_run_changes_nothing, test_rules_purchase::test_one_request_that_fails_does_not_stop_the_others |
| PR-15 | A quotation, a request for quotation and an order can be made only from a submitted purchase request, and take its cost center | `overrides/material_request.py::make_supplier_quotation`, `overrides/material_request.py::make_request_for_quotation`, `overrides/material_request.py::make_purchase_order` | test_budget_integration::test_l4_procurement_user_can_raise_po_from_approved_pr |
| PR-16 | The printed request shows the month of its transaction date | `custom_app/print_format/material_request_print_format/material_request_print_format.json` | test_budget_integration::test_a4_print_format_shows_transaction_month, test_budget_integration::test_m3_mat_mr_2026_02080_prints_october |
| PR-17 | On the form, a user with an employee record can pick only themselves, and the approver comes from the employee's expense approver | `public/js/material_request.js` | - |

## SQ Quotations

| ID | Rule | Home | Test |
| --- | --- | --- | --- |
| SQ-01 | A quotation row may equal its request row's amount but not exceed it. A row with no row link is matched by its item, and a row with no request is not checked | `api/material_request.py::validate_quotation_against_material_request`, `api/material_request.py::get_material_request_item_amount` | test_budget_integration::test_k2_quotation_above_pr_amount_is_blocked, test_rules_purchase::test_a_quotation_may_equal_the_request_but_not_exceed_it, test_rules_purchase::test_a_row_without_a_row_link_is_checked_by_its_item, test_rules_purchase::test_a_row_without_a_request_is_not_checked |
| SQ-02 | Every row takes the quotation's cost center | `api/supplier_quotation.py::update_item_cost_center` | test_rules_purchase::test_the_quotations_cost_center_is_put_on_every_row |
| SQ-03 | A new quotation is Not Ordered. A status already there is kept | `api/supplier_quotation.py::set_default_order_status` | test_rules_purchase::test_a_new_quotation_is_not_ordered |
| SQ-04 | Submitting an order adds its quantity to the quotation row. The quotation is then Partially Ordered, or Completely Ordered when every row is | `api/supplier_quotation.py::update_ordered_qty_on_po_submit`, `api/supplier_quotation.py::_recompute_order_status` | test_rules_purchase::test_submitting_orders_moves_the_quotation_to_completely_ordered |
| SQ-05 | Cancelling an order takes its quantity back, never below zero | `api/supplier_quotation.py::update_ordered_qty_on_po_cancel`, `api/supplier_quotation.py::_apply_po_ordered_qty` | test_rules_purchase::test_cancelling_an_order_takes_its_quantity_back_and_never_below_zero |
| SQ-06 | A quotation made from a request for quotation is for the chosen vendor, keeps the cost center and links each row back | `overrides/rfq.py::make_supplier_quotation_from_rfq` | test_budget_integration::test_k1_rfq_route_makes_quotation_for_supplier |
| SQ-07 | On the form, choosing a vendor keeps the rates that came from the request | `public/js/supplier_quotation.js` | - |

## PO Purchase orders and receipts

| ID | Rule | Home | Test |
| --- | --- | --- | --- |
| PO-01 | Every order row needs a purchase request | `api/purchase_order.py::validate_po_items` | test_rules_purchase::test_every_order_row_needs_a_purchase_request |
| PO-02 | With no quotation, the vendor must be the item's default supplier in the company. With a quotation, any vendor may be ordered from | `api/purchase_order.py::validate_po_items` | test_budget_integration::test_po_with_wrong_supplier_and_no_quotation_is_blocked, test_rules_purchase::test_without_a_quotation_only_the_items_default_supplier_may_be_ordered_from, test_rules_purchase::test_with_a_quotation_any_supplier_may_be_ordered_from |
| PO-03 | A row's expense account must match its request row | `api/purchase_order.py::validate_po_items` | test_budget_integration::test_k3_po_expense_account_must_match_pr, test_rules_purchase::test_an_orders_expense_account_must_match_the_request |
| PO-04 | Every row takes the order's cost center, which is mandatory on the quotation, order, receipt and invoice | `api/purchase_order.py::validate_po_items`, `custom_app/custom/purchase_order.json` | test_rules_purchase::test_the_orders_cost_center_is_put_on_every_row, test_rules_purchase::test_the_cost_center_is_mandatory_along_the_whole_chain |
| PO-05 | Every receipt row needs a purchase order | `custom_app/custom/purchase_receipt_item.json` | test_rules_purchase::test_a_receipt_row_needs_a_purchase_order |

## PI Purchase invoices

| ID | Rule | Home | Test |
| --- | --- | --- | --- |
| PI-01 | Every invoice row needs a purchase order | `api/purchase_invoice.py::validate_pi_items`, `custom_app/custom/purchase_invoice_item.json` | test_budget_integration::test_k4_invoice_without_po_is_blocked, test_rules_purchase::test_every_invoice_row_needs_a_purchase_order |
| PI-02 | A row's expense account must match its order row and its request row | `api/purchase_invoice.py::validate_pi_items` | test_rules_purchase::test_an_invoices_expense_account_must_match_the_order, test_rules_purchase::test_an_invoices_expense_account_must_match_the_request |
| PI-03 | A submitted invoice books the expense to the request's account and cost center | `api/purchase_invoice.py::validate_pi_items` | test_budget_integration::test_d2_invoice_books_expense_to_pr_account_and_cost_center |
| PI-04 | Category and Planned Payment Date can be changed after submit | `custom_app/custom/purchase_invoice.json` | test_rules_purchase::test_category_and_planned_payment_date_can_change_after_submit |

## PE Payments

| ID | Rule | Home | Test |
| --- | --- | --- | --- |
| PE-01 | A payment to an employee needs at least one reference | `api/payment_entry.py::validate` | test_budget_integration::test_k8_employee_payment_without_reference_is_blocked, test_budget_integration::test_k8_expense_claim_paid_through_payment_entry, test_rules_purchase::test_an_employee_payment_needs_a_reference |
| PE-02 | A payment to a supplier needs at least one reference and no unallocated amount. Other payments are not limited | `api/payment_entry.py::validate` | test_budget_integration::test_supplier_payment_without_reference_is_blocked, test_budget_integration::test_supplier_payment_with_unallocated_amount_is_blocked, test_rules_purchase::test_a_supplier_payment_needs_a_reference_and_nothing_unallocated, test_rules_purchase::test_a_customer_payment_needs_no_reference |
| PE-03 | A payment records who saved it and when, and who approved it and when | `api/payment_entry.py::before_save`, `api/payment_entry.py::before_submit` | test_rules_purchase::test_a_payment_keeps_who_made_it_and_who_approved_it |

## EC Expense claims

| ID | Rule | Home | Test |
| --- | --- | --- | --- |
| EC-01 | A claim and its rows take the cost center of the employee's department, which are mandatory | `api/expense_claim.py::update_item_cost_center`, `public/js/expense_claim.js` | test_rules_purchase::test_a_claim_takes_the_cost_center_of_the_employees_department, test_rules_purchase::test_a_claim_needs_a_department_and_its_cost_center, test_rules_purchase::test_the_cost_center_is_mandatory_on_a_claim_and_its_rows |
| EC-02 | An active fiscal year must cover the claim's date | `api/expense_claim.py::update_item_cost_center` | test_rules_purchase::test_a_claim_needs_an_active_fiscal_year_on_its_date |
| EC-03 | The claim type needs a default account in the company | `api/expense_claim.py::update_item_cost_center` | test_rules_purchase::test_a_claim_type_needs_an_account_in_the_company |
| EC-04 | A submitted Budget must exist for the account, cost center, company and year | `api/expense_claim.py::update_item_cost_center` | test_rules_purchase::test_a_claim_needs_a_submitted_budget_on_its_account_and_cost_center |
| EC-05 | No one approves or rejects their own claim | `overrides/expense_claim.py::CustomExpenseClaim` | test_budget_integration::test_k9_employee_cannot_approve_own_claim, test_rules_purchase::test_no_one_approves_their_own_claim |
| EC-06 | A new claim emails its approver | `api/expense_claim.py::notify_approver_on_create` | test_rules_purchase::test_a_new_claim_emails_its_approver |
| EC-07 | The employee is emailed once when the claim is approved or rejected | `api/expense_claim.py::on_workflow_state_change` | test_rules_purchase::test_the_employee_is_told_once_when_a_claim_is_approved_or_rejected |

## AT Attendance and shifts

| ID | Rule | Home | Test |
| --- | --- | --- | --- |
| AT-01 | A check-in needs an employee | `api/employee_checkin.py::before_insert_checkin` | test_rules_people::test_a_check_in_needs_an_employee |
| AT-02 | A check-in from the HR app is refused unless the employee is allowed to check in from it | `api/employee_checkin.py::before_insert_checkin` | test_rules_people::test_the_hr_app_takes_check_ins_only_from_those_allowed |
| AT-03 | The first, third and fifth Saturdays of a month are found by counting its Saturdays | `utils/saturday_utils.py::is_first_third_fifth_saturday` | test_rules_people::test_first_third_and_fifth_saturdays_are_found |
| AT-04 | On those Saturdays, attendance of companies other than the two teaching companies is saved as Absent and marked Weekly Off (Auto) | `overrides/attendance.py::CustomAttendance` | test_rules_people::test_on_those_saturdays_other_companies_are_marked_absent, test_rules_people::test_the_two_teaching_companies_keep_their_saturday_attendance |
| AT-05 | An attendance request takes the shift of each of its days from the Shift Assignment or the employee's default. A request over two shifts is refused, and days with no shift leave it empty | `api/attendance_request.py::set_shift`, `api/attendance_request.py::_resolve_shift_for_date`, `api/attendance_request.py::get_shift_preview`, `public/js/attendance_request.js` | test_rules_people::test_the_shift_comes_from_the_shift_of_each_day, test_rules_people::test_a_request_over_two_shifts_must_be_split, test_rules_people::test_days_with_no_shift_leave_it_empty, test_rules_people::test_the_preview_shows_a_shift_only_when_there_is_one |
| AT-06 | The shift is worked out again when the request is approved | `api/attendance_request.py::lock_shift_before_submit` | test_rules_people::test_the_shift_is_worked_out_again_at_approval |
| AT-07 | The request is shared with the employee's leave approver, with submit rights, unless they can act on it already. A former approver loses it when the employee changes | `api/attendance_request.py::share_with_leave_approver` | test_rules_people::test_the_leave_approver_gets_the_request_with_submit_rights, test_rules_people::test_an_approver_who_can_already_act_gets_no_share, test_rules_people::test_a_former_approver_loses_the_request |
| AT-08 | No one approves or rejects their own shift request | `overrides/shift_request.py::CustomShiftRequest` | test_rules_people::test_no_one_approves_their_own_shift_request |
| AT-09 | The attendance sheet shows each day as a payroll code: present, on duty, absent, half day, leave by type, week off or public holiday | `custom_app/doctype/attendance_excel_generator/attendance_excel_generator.py::generate_excel`, `custom_app/doctype/attendance_excel_generator/attendance_excel_generator.py::map_leave_code`, `custom_app/doctype/attendance_excel_generator/attendance_excel_generator.py::get_holiday_code` | test_rules_people::test_leave_types_become_payroll_codes, test_rules_people::test_a_holiday_is_a_week_off_or_a_public_holiday, test_rules_people::test_each_day_shows_its_attendance_code |
| AT-10 | The sheet leaves days before joining and after leaving blank. Someone not employed in the period, or not active with no leaving date, is left out | `custom_app/doctype/attendance_excel_generator/attendance_excel_generator.py::generate_excel` | test_rules_people::test_days_before_joining_and_after_leaving_are_blank, test_rules_people::test_someone_who_left_with_no_date_or_was_not_employed_is_left_out |

## LV Leave, probation and contracts

| ID | Rule | Home | Test |
| --- | --- | --- | --- |
| LV-01 | No one approves or rejects their own leave | `overrides/leave_application.py::CustomLeaveApplication` | test_rules_people::test_no_one_approves_their_own_leave |
| LV-02 | On the day probation ends, an employee of the two teaching companies gets earned leave for the rest of the leave year, pro rata of 18 days, once | `tasks/end_probation.py::allocate_earned_leaves_on_probation_end` | test_rules_people::test_earned_leave_is_given_for_the_rest_of_the_year_on_the_day_probation_ends, test_rules_people::test_only_the_two_teaching_companies_get_it, test_rules_people::test_it_is_given_once |
| LV-03 | The leave year ends on the next 31 March | `tasks/end_probation.py::get_financial_year_for_probation` | test_rules_people::test_the_year_for_leave_ends_on_the_next_31_march |
| LV-04 | On the first of each month, managers and the Head-HR are emailed the active employees of the two teaching companies whose probation ends this month or next | `tasks/probation_reminder.py::send_probation_end_alerts` | test_rules_people::test_managers_and_head_hr_hear_of_probations_ending_this_month_or_next, test_rules_people::test_no_one_is_emailed_when_nothing_ends |
| LV-05 | On the first of each month, they are emailed the contracts that end this month or next in the same way | `tasks/employee_contract_expiry_alert.py::send_contract_expiry_alerts` | test_rules_people::test_managers_and_head_hr_hear_of_contracts_ending_this_month_or_next |

## PY Salary slips and payslip import

| ID | Rule | Home | Test |
| --- | --- | --- | --- |
| PY-01 | An emailed salary slip carries its own letter head | `overrides/salary_slip.py::CustomSalarySlip` | test_rules_people::test_the_emailed_slip_carries_its_own_letter_head |
| PY-02 | With no preferred email on the employee, the slip is not sent and the user is told | `overrides/salary_slip.py::email_salary_slip` | test_rules_people::test_without_a_preferred_email_nothing_is_sent |
| PY-03 | Only System Managers, HR Managers and HR Users import payslips | `custom_app/page/payslip_uploader/payslip_uploader.py::start_import`, `custom_app/page/payslip_uploader/payslip_uploader.py::get_import_status` | test_rules_people::test_only_hr_and_system_managers_may_import |
| PY-04 | In a combined batch the file name says whether a file is a salary slip or a tax sheet. In a single kind of batch the batch says so. A file that does not fit, or names an unknown month, is skipped | `api/paysquare_payslip_import_utils.py::parse_filename` | test_rules_people::test_a_combined_batch_reads_the_kind_from_the_file_name, test_rules_people::test_a_combined_batch_skips_a_file_that_does_not_say_its_kind, test_rules_people::test_a_single_kind_batch_takes_its_kind_from_the_batch, test_rules_people::test_an_unknown_month_is_skipped |
| PY-05 | Each file is attached, as a private file, to the record of its employee, month and year | `api/paysquare_payslip_import_utils.py::create_or_update_record`, `api/paysquare_payslip_import_utils.py::find_employee` | test_rules_people::test_each_file_is_attached_to_its_employees_record |
| PY-06 | A batch needs a known kind and a password. Only PDFs are counted, and a zip with AES encryption is not supported | `api/paysquare_payslip_import_utils.py::process_zip_file`, `api/paysquare_payslip_import_utils.py::count_pdf_entries`, `api/paysquare_payslip_import_utils.py::_is_aes_encrypted` | test_rules_people::test_a_batch_needs_a_known_kind_and_a_password, test_rules_people::test_only_pdfs_are_counted, test_rules_people::test_aes_zips_are_recognised |
| PY-07 | Files that cannot be used are skipped and written to one Error Log entry per batch | `api/paysquare_payslip_import_utils.py::_log_batch_issues` | test_rules_people::test_files_that_cannot_be_used_are_skipped_and_logged_once |
| PY-08 | Up to ten files are processed at once and more in the background. The uploaded zip is deleted afterwards | `custom_app/page/payslip_uploader/payslip_uploader.py::start_import`, `custom_app/page/payslip_uploader/payslip_uploader.py::run_import_job` | test_rules_people::test_up_to_ten_files_run_at_once_and_more_in_the_background, test_rules_people::test_the_uploaded_zip_is_deleted_afterwards |

## WF Approval workflows

| ID | Rule | Home | Test |
| --- | --- | --- | --- |
| WF-01 | Requests, orders, invoices, payments, claims, budget uploads, reallocations and Master Budgets each have one active workflow | `fixtures/workflow.json` | test_rules_access::test_each_document_has_one_active_workflow |
| WF-02 | A request and a claim are approved by the Expense Approver, an order by the Procurement Approver, an invoice and the budget documents by the Finance Approver, a payment by the AP Manager. Other roles cannot | `fixtures/workflow.json` | test_budget_integration::test_l6_employee_cannot_approve_a_pr, test_budget_integration::test_l7_assigned_approver_can_approve, test_budget_integration::test_l8_finance_user_cannot_approve_reallocation, test_budget_integration::test_l9_ap_user_cannot_approve_payment, test_rules_access::test_each_document_is_approved_by_its_own_role |
| WF-03 | No one approves or rejects a draft they made themselves | `fixtures/workflow.json` | test_rules_access::test_no_one_approves_their_own_draft |
| WF-04 | A request with a verifier is verified before it is approved. Without one it is approved directly | `fixtures/workflow.json` | test_budget_integration::test_k6_verifier_cost_center_needs_verify_then_approve, test_rules_access::test_a_request_with_a_verifier_is_verified_before_approval, test_rules_access::test_a_request_without_a_verifier_is_approved_directly |
| WF-05 | A claim is approved by the manager and then by finance, neither of whom may be its maker. Finance rejecting it cancels it | `fixtures/workflow.json` | test_rules_access::test_a_claim_is_approved_by_the_manager_and_then_by_finance, test_rules_access::test_a_claim_finance_rejects_is_cancelled |
| WF-06 | An approved document is submitted and a rejected one stays a draft. A rejected claim is submitted as rejected | `fixtures/workflow.json` | test_rules_access::test_an_approved_document_is_submitted_and_a_rejected_one_stays_a_draft, test_rules_access::test_a_rejected_claim_is_submitted_as_rejected |
| WF-07 | An approved Budget Reallocation cannot be cancelled through its workflow | `fixtures/workflow.json` | test_rules_access::test_a_reallocation_cannot_be_cancelled |

## AC Who sees what

| ID | Rule | Home | Test |
| --- | --- | --- | --- |
| AC-01 | System Managers and Auditors list every request and claim. A user with none of the roles lists nothing | `permissions/material_request.py::material_request_permission_query`, `permissions/expense_claim.py::expense_claim_permission_query` | test_rules_access::test_system_managers_and_auditors_list_everything, test_rules_access::test_a_user_with_no_role_lists_nothing |
| AC-02 | Procurement Users list approved requests, Expense Approvers those they approve or verify, employees their own. A user with two roles lists what either lists | `permissions/material_request.py::material_request_permission_query` | test_budget_integration::test_l1_employee_lists_only_own_prs, test_budget_integration::test_l2_approver_lists_prs_assigned_to_them, test_budget_integration::test_l3_procurement_user_lists_only_approved_prs, test_rules_access::test_who_lists_which_purchase_requests, test_rules_access::test_two_roles_list_what_either_lists, test_rules_access::test_an_employee_role_without_an_employee_record_lists_nothing |
| AC-03 | Finance Approvers list approved, finance approved and cancelled claims, AP Users and AP Managers the finance approved ones, Expense Approvers those they approve, employees their own | `permissions/expense_claim.py::expense_claim_permission_query` | test_rules_access::test_who_lists_which_expense_claims |
| AC-04 | These filters apply to lists. Opening a document follows the role's permissions | `permissions/material_request.py::material_request_permission_query` | test_budget_integration::test_l4_access_rules_filter_lists_only, test_budget_integration::test_l4_right_people_can_open_a_pr, test_budget_integration::test_l5_right_people_can_open_a_claim |
| AC-05 | A salary slip is listed and opened only by its employee, HR Managers and System Managers | `permissions/salary_slip.py::salary_slip_permission_query`, `permissions/salary_slip.py::has_permission` | test_rules_access::test_salary_slips_are_listed_only_to_their_employee, test_rules_access::test_a_salary_slip_opens_only_for_its_employee |
| AC-06 | A WorkBoard task is listed to who gave it and who does it | `permissions/wb_task.py::wb_task_permission_query` | test_rules_access::test_a_workboard_task_is_listed_to_who_gave_it_and_who_does_it |
| AC-07 | Saving a user limits an employee to their own record and company. HR and Admin profiles lose the employee limit and get the other companies' mailboxes. A user with no employee record is left alone | `api/user_permission.py::manage_user_permissions` | test_rules_access::test_an_employee_is_limited_to_their_own_record, test_rules_access::test_an_employee_keeps_only_their_own_company, test_rules_access::test_hr_and_admin_lose_the_employee_limit_and_get_every_other_company_mailbox, test_rules_access::test_a_user_with_no_employee_record_is_left_alone |

## ED EOMS documents

| ID | Rule | Home | Test |
| --- | --- | --- | --- |
| ED-01 | Every Desk user reads EOMS Docs, EOMS Department and EOMS Sub Department. Only System Managers create, change or delete them, so only they see the New button | `custom_app/doctype/eoms_docs/eoms_docs.json`, `custom_app/doctype/eoms_department/eoms_department.json`, `custom_app/doctype/eoms_sub_department/eoms_sub_department.json` | test_rules_eoms::test_everyone_reads_and_only_system_managers_change |
| ED-02 | Company and Department are mandatory, Sub-Department is not. Department and Sub-Department link to EOMS Department and EOMS Sub Department, which hold only a name and are apart from ERPNext's Department | `custom_app/doctype/eoms_docs/eoms_docs.json`, `custom_app/doctype/eoms_department/eoms_department.json`, `custom_app/doctype/eoms_sub_department/eoms_sub_department.json` | test_rules_eoms::test_company_and_department_are_mandatory, test_rules_eoms::test_departments_hold_only_a_name |
| ED-03 | Upload Doc is mandatory and must be a private PDF, DOC or DOCX file whose content is of that kind. Its file name becomes the Document Name | `custom_app/doctype/eoms_docs/eoms_docs.py::check_upload`, `custom_app/doctype/eoms_docs/eoms_docs.js` | test_rules_eoms::test_only_pdf_doc_or_docx_is_accepted, test_rules_eoms::test_the_file_must_be_private, test_rules_eoms::test_a_renamed_file_is_refused |
| ED-04 | Readers see the document only as page images drawn on the server. The file never reaches them, and Upload Doc shows only to System Managers. Someone who may not read the record gets no page | `custom_app/doctype/eoms_docs/eoms_docs.py::get_pages`, `custom_app/doctype/eoms_docs/eoms_docs.py::get_page`, `custom_app/doctype/eoms_docs/eoms_docs.py::readable_pdf`, `custom_app/doctype/eoms_docs/eoms_docs.json` | test_rules_eoms::test_a_page_is_sent_as_an_image_never_the_file, test_rules_eoms::test_only_system_managers_see_the_file_field, test_rules_eoms::test_someone_who_cannot_read_the_record_sees_no_page, test_rules_eoms::test_a_page_that_is_not_there |
| ED-05 | Only System Managers download a file attached to EOMS Docs. Its link, Frappe's download, the zip of several files and the File record refuse everyone else. Files of other records are not changed | `overrides/file.py::CustomFile`, `overrides/file.py::may_download`, `overrides/file.py::has_permission`, `overrides/file.py::zip_files` | test_rules_eoms::test_readers_cannot_download_an_eoms_file, test_rules_eoms::test_files_of_other_records_follow_frappe, test_rules_eoms::test_the_file_record_is_closed_to_readers, test_rules_eoms::test_a_zip_leaves_out_eoms_files, test_rules_eoms::test_every_way_frappe_hands_out_a_file_is_covered |
| ED-06 | Pages load as the reader scrolls, a page when it comes near. Each is drawn as wide as the screen needs, rounded up to a few widths, and the browser keeps it for a day | `custom_app/doctype/eoms_docs/eoms_docs.js`, `custom_app/doctype/eoms_docs/eoms_docs.py::fit` | test_rules_eoms::test_pages_are_laid_out_before_they_are_drawn, test_rules_eoms::test_page_widths_are_rounded_up_to_a_few, test_rules_eoms::test_pages_load_only_when_scrolled_near |
| ED-07 | A Word file is shown through a PDF that LibreOffice makes on save, kept as a private file of the record. Without LibreOffice, or when it fails, the save is refused. A PDF is shown as it is | `custom_app/doctype/eoms_docs/eoms_docs.py::make_preview`, `custom_app/doctype/eoms_docs/eoms_docs.py::to_pdf`, `custom_app/doctype/eoms_docs/eoms_docs.py::drop_preview` | test_rules_eoms::test_a_word_file_gets_a_pdf_to_show, test_rules_eoms::test_without_libreoffice_a_word_file_is_refused, test_rules_eoms::test_a_pdf_is_shown_as_it_is, test_rules_eoms::test_a_word_file_is_shown_from_its_pdf |
| ED-08 | The EOMS Docs entry in the sidebar, between HR and Vendor & Assets, opens the list for everyone. When those two share a place, Vendor & Assets is moved down. It is put back after each migrate | `sidebar.py::add_entries`, `sidebar.py::place`, `sidebar.py::set_entry` | test_rules_eoms::test_eoms_docs_goes_between_hr_and_vendor_and_assets, test_rules_eoms::test_the_eoms_entry_opens_the_list_for_everyone, test_rules_eoms::test_an_eoms_entry_in_place_moves_nothing, test_rules_eoms::test_without_hr_the_eoms_entry_goes_last |

## VN Vendors

| ID | Rule | Home | Test |
| --- | --- | --- | --- |
| VN-01 | A new vendor's code is the company, the year and a running number: DSJ, CDE, VU or GEN | `api/supplier.py::set_vendor_code` | test_rules_access::test_a_vendor_code_is_company_year_and_number, test_rules_access::test_the_number_follows_the_last_vendor_of_the_company_and_year |
| VN-02 | A vendor must have its company, PAN, contact, address and bank details. The vendor form on the website asks for the same | `custom_app/custom/supplier.json`, `custom_app/web_form/vendor_details/vendor_details.json` | test_rules_access::test_a_vendor_must_have_tax_contact_and_bank_details, test_rules_access::test_the_vendor_form_asks_for_the_same_details |

## EM Emails and letter heads

| ID | Rule | Home | Test |
| --- | --- | --- | --- |
| EM-01 | An outgoing email uses the account of the company of its document, or of the sender's own company. Received emails and companies with no account are left alone | `api/email.py::set_company_email_account` | test_rules_access::test_an_email_goes_out_from_the_documents_companys_account, test_rules_access::test_without_a_document_the_senders_own_company_is_used, test_rules_access::test_received_emails_and_companies_with_no_account_are_left_alone |
| EM-02 | Each person gets a notification once, and a failed email never stops the document | `api/notification_utils.py::safe_sendmail` | test_rules_access::test_each_person_gets_a_notification_once, test_rules_access::test_a_failed_email_never_stops_the_document |
| EM-03 | Requests, orders, receipts, invoices and salary slips take their company's letter head when new or when the company changes. A company without one leaves it alone | `api/letter_head.py::set_letter_head` | test_rules_access::test_a_new_document_takes_its_companys_letter_head, test_rules_access::test_a_saved_document_changes_it_only_with_its_company, test_rules_access::test_a_company_without_one_leaves_the_letter_head_alone |

## DB Dashboards

| ID | Rule | Home | Test |
| --- | --- | --- | --- |
| DB-01 | On every dashboard a System Manager sees every company | `custom_app/page/hr_dashboard/hr_dashboard.py::_resolve_company`, `custom_app/page/finance_dashboard/finance_dashboard.py::_enforce_company`, `custom_app/page/purchase_timeline/purchase_timeline.py::_get_permitted_companies` | test_rules_access::test_a_system_manager_sees_every_company |
| DB-02 | An Institution Head is kept to the companies of their user permissions | `custom_app/page/hr_dashboard/hr_dashboard.py::_resolve_company`, `custom_app/page/finance_dashboard/finance_dashboard.py::_company_where`, `custom_app/page/purchase_timeline/purchase_timeline.py::_get_permitted_companies` | test_rules_access::test_an_institution_head_is_kept_to_their_companies |
| DB-03 | With no company permission, the HR and Finance dashboards show nothing, and the Purchase Timeline shows every company | `custom_app/page/hr_dashboard/hr_dashboard.py::_resolve_company`, `custom_app/page/finance_dashboard/finance_dashboard.py::_company_where`, `custom_app/page/purchase_timeline/purchase_timeline.py::_get_permitted_companies` | test_rules_access::test_with_no_company_permission_hr_and_finance_show_nothing, test_rules_access::test_with_no_company_permission_the_purchase_timeline_shows_all |
| DB-04 | The Purchase Timeline is refused to roles other than System Manager and Institution Head | `custom_app/page/purchase_timeline/purchase_timeline.py::_get_permitted_companies` | test_rules_access::test_the_purchase_timeline_is_refused_to_other_roles |
| DB-05 | A period is the present calendar month, quarter or year, or the dates given | `custom_app/page/hr_dashboard/hr_dashboard.py::_period_dates` | test_rules_access::test_a_period_is_this_month_quarter_or_year |
| DB-06 | Creditors are aged in steps of thirty days, up to more than 120 | `custom_app/page/finance_dashboard/finance_dashboard.py::get_creditor_ageing` | test_rules_access::test_creditors_age_in_thirty_day_steps |
| DB-07 | Vendor risk is High when the top three vendors have more than 40 percent of the spend, Medium above 25, else Low | `custom_app/page/finance_dashboard/finance_dashboard.py::get_vendor_concentration` | test_rules_access::test_vendor_risk_is_the_share_of_the_top_three |
| DB-08 | The Asset Dashboard is for System Managers and Asset Managers. The budget file format can be downloaded by System Managers and the finance roles | `custom_app/page/asset_dashboard/asset_dashboard.json`, `custom_app/page/download_budget_exce/download_budget_exce.json` | - |

## ST Set up on the site

| ID | Rule | Home | Test |
| --- | --- | --- | --- |
| ST-01 | All three Budget Settings switches are on: backdated requests refused, the month's own budget only, and the transaction date decides the month. No effective date is set | the site | seen on the site, 2026-11-25 |
| ST-02 | A script refuses a request dated more than thirty days back. The backdated rule BC-14 is stricter, so it has no effect while that is on | the site | seen on the site, 2026-11-25 |
| ST-03 | Scripts and form scripts fill the fiscal year of a request, order and invoice from its date | the site | seen on the site, 2026-11-25 |
| ST-04 | The total value of a request is the sum of its row amounts, worked out on the form | the site | seen on the site, 2026-11-25 |
| ST-05 | On an order or invoice form, changing a row's amount works out the quantity as amount divided by rate | the site | seen on the site, 2026-11-25 |
| ST-06 | Setting an employee to Inactive, Left or Suspended disables their user, and Active enables it. It happens on the form only | the site | seen on the site, 2026-11-25 |
| ST-07 | A new employee with a user gets the roles of the role profile of their designation | the site | seen on the site, 2026-11-25 |
| ST-08 | A leave application that is open emails the leave approver | the site | seen on the site, 2026-11-25 |
| ST-09 | Job Requisition has a workflow with the states Draft, Pending, Approved and Rejected | the site | seen on the site, 2026-11-25 |
| ST-10 | Scripts remind employees who have not checked in by 11:00 or not checked out by 20:00, except on leave and holidays. Both jobs are stopped, so no reminder goes out | the site | seen on the site, 2026-11-25 |
| ST-11 | Attendance is marked from check-ins by each Shift Type, with its own hours for a half day and an absence | the site | seen on the site, 2026-11-25 |
| ST-12 | Buying Settings ask for an order before an invoice, and stop a rate that differs along the purchase chain | the site | seen on the site, 2026-11-25 |
| ST-13 | HR Settings make the leave and expense approver mandatory and stop anyone from approving their own leave | the site | seen on the site, 2026-11-25 |
| ST-14 | Payroll is based on attendance, an unmarked day counts as present, and a submitted slip is emailed to the employee | the site | seen on the site, 2026-11-25 |
| ST-15 | Mandatory fields added on the site include notes on an order, the attachment on an invoice and the transaction reference number on a payment | the site | seen on the site, 2026-11-25 |
| ST-16 | A check-in must say in or out, and its time cannot be changed on the form | the site | seen on the site, 2026-11-25 |
| ST-17 | An employee cannot edit an investment declaration on the form after its lock date | the site | seen on the site, 2026-11-25 |
| ST-18 | A form script numbers a vendor by its vendor group. For a new vendor the app's code replaces it, see VN-01 | the site | seen on the site, 2026-11-25 |

## XX Keeping rules true

| ID | Rule | Home | Test |
| --- | --- | --- | --- |
| XX-01 | Every rule has its own ID, and every group is on one tab of the page | `business_rules/catalogue.py::TABS` | test_rules_policy::test_ids_are_unique, test_rules_policy::test_every_group_is_on_one_tab |
| XX-02 | Every test a rule names exists, and every test belongs to a rule | `business_rules/catalogue.py::test_names` | test_rules_policy::test_every_rule_names_tests_that_exist, test_rules_policy::test_every_test_belongs_to_a_rule |
| XX-03 | The code a rule names exists, and every function in hooks.py is named by a rule | `business_rules/catalogue.py::code_names` | test_rules_policy::test_the_code_a_rule_names_exists, test_rules_policy::test_every_hook_is_a_rule |
| XX-04 | Every rule has plain words written from its present text | `business_rules/catalogue.py::fingerprint` | test_rules_policy::test_plain_words_are_written_from_the_present_rule, test_rules_policy::test_plain_words_name_no_code |
| XX-05 | The rules hold no email address, PAN, GSTIN, phone number or key | `business_rules/RULES.md` | test_rules_policy::test_the_rules_hold_no_personal_data |
| XX-06 | Only a System Manager opens the page and reads its data. Its shortcut on Home shows to System Managers only. Its sidebar entry, right below Config Email, shows to System Managers and, as Frappe lists every entry for them, to Workspace Managers. Both are put back after each migrate | `custom_app/page/business_rules/business_rules.py::get`, `custom_app/page/business_rules/business_rules.json`, `business_rules/shortcut.py::add_to_home`, `business_rules/shortcut.py::add_shortcut`, `sidebar.py::add_entries`, `sidebar.py::set_entry`, `sidebar.py::place` | test_rules_page::test_only_a_system_manager_reads_the_rules, test_rules_page::test_the_page_opens_only_for_system_managers, test_rules_page::test_the_page_shows_every_rule, test_rules_page::test_the_shortcut_goes_after_homes_last_shortcut, test_rules_page::test_a_shortcut_already_there_is_not_added_again, test_rules_page::test_the_shortcut_never_stops_a_migrate, test_rules_page::test_the_sidebar_entry_opens_the_page_for_system_managers, test_rules_page::test_the_entry_goes_right_below_config_email, test_rules_page::test_without_config_email_the_entry_goes_last, test_rules_page::test_an_entry_already_in_place_is_not_saved_again, test_rules_page::test_the_sidebar_entry_never_stops_a_migrate |
| XX-07 | The page compares the site with the app: workflows, scripts, notifications, mandatory fields and overrides, and shows no field's value | `business_rules/site.py::live` | test_rules_page::test_a_workflow_is_compared_with_the_app, test_rules_page::test_a_stopped_or_failing_job_is_shown, test_rules_page::test_fields_the_app_does_not_hold_are_shown_without_their_value, test_rules_page::test_switched_off_scripts_are_not_shown, test_rules_page::test_settings_are_shown_as_they_are |
