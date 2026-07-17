# Sample Access Database Creation

On a Windows machine with Microsoft Access or the Access Database Engine installed:

1. Create `iam_automation.accdb` in the local OneDrive-synced SharePoint folder.
2. Add an `app_metadata` table with:
   - `metadata_key` short text, primary key.
   - `metadata_value` long text.
   - `updated_at` date/time.
3. Add an `approved_users` table with:
   - `username` short text, primary key.
   - `roles` long text.
   - `active` yes/no.
4. Add an `employee` table with:
   - `employee_id` short text, primary key.
   - `full_name` short text.
   - `email` short text.
   - `manager_employee_id` short text.
   - `vendor` short text.
   - `business_unit` short text.
   - `location` short text.
   - `employment_status` short text.
   - `start_date` date/time.
   - `end_date` date/time.
   - `record_version` number.
   - `created_at` date/time.
   - `created_by` short text.
   - `modified_at` date/time.
   - `modified_by` short text.

The POC scripts will later automate this once driver behavior is validated in the target environment.
