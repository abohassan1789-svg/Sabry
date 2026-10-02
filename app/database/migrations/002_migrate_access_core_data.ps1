param(
    [string]$AccessPath = "D:\CRM\HA CODEM04.accdb",
    [string]$PsqlPath = "C:\Program Files\PostgreSQL\18\bin\psql.exe",
    [string]$PgHost = "localhost",
    [string]$PgUser = "postgres",
    [string]$PgDatabase = "crm",
    [string]$PgPassword = "",
    [string]$WorkDir = "D:\CRM\CRM_PYTHON_APP_STRUCTURE\app\database\migrations\.tmp_access_export"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $AccessPath)) {
    throw "Access database not found: $AccessPath"
}

if (-not (Test-Path -LiteralPath $PsqlPath)) {
    throw "psql not found: $PsqlPath"
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

function Convert-ToCsvValue {
    param([object]$Value)

    if ($null -eq $Value -or $Value -is [System.DBNull]) {
        return "\N"
    }

    if ($Value -is [bool]) {
        if ($Value) { return '"true"' }
        return '"false"'
    }

    if ($Value -is [datetime]) {
        return '"' + $Value.ToString("yyyy-MM-dd HH:mm:ss") + '"'
    }

    $text = [string]$Value
    $text = $text.Replace('"', '""')
    return '"' + $text + '"'
}

function Export-AccessQueryToCsv {
    param(
        [System.Data.Odbc.OdbcConnection]$Connection,
        [string]$Sql,
        [string[]]$Columns,
        [string[]]$ReadColumns = $Columns,
        [string]$CsvPath
    )

    $cmd = $Connection.CreateCommand()
    $cmd.CommandText = $Sql
    $reader = $cmd.ExecuteReader()

    $encoding = New-Object System.Text.UTF8Encoding($false)
    $writer = New-Object System.IO.StreamWriter($CsvPath, $false, $encoding)
    try {
        $writer.WriteLine(($Columns | ForEach-Object { '"' + $_ + '"' }) -join ",")

        while ($reader.Read()) {
            $values = foreach ($column in $ReadColumns) {
                Convert-ToCsvValue $reader[$column]
            }
            $writer.WriteLine(($values -join ","))
        }
    }
    finally {
        $reader.Close()
        $writer.Close()
    }
}

function Invoke-Psql {
    param([string[]]$PsqlArgs)

    $env:PGPASSWORD = $PgPassword
    & $PsqlPath @PsqlArgs
    if ($LASTEXITCODE -ne 0) {
        throw "psql failed with exit code $LASTEXITCODE"
    }
}

$tables = @(
    @{
        PgTable = "places"
        CsvName = "places.csv"
        Columns = @("place_id", "place_number")
        AccessSql = @"
SELECT
    [id] AS [place_id],
    [place12] AS [place_number]
FROM [EBplace]
"@
    },
    @{
        PgTable = "customers"
        CsvName = "customers.csv"
        Columns = @(
            "customer_id", "phone_number", "customer_name", "place_area_feddan",
            "area_number", "building", "unit_number", "floor_number",
            "installment_duration_years", "remaining_installments",
            "installment_amount", "legacy_area_number_2"
        )
        AccessSql = @"
SELECT
    [id] AS [customer_id],
    [Phpne] AS [phone_number],
    [CUstomerN] AS [customer_name],
    [placeFadan] AS [place_area_feddan],
    [PlaceNumber] AS [area_number],
    [Bild] AS [building],
    [Unit] AS [unit_number],
    [Door] AS [floor_number],
    [ModQessd] AS [installment_duration_years],
    [motapQessd] AS [remaining_installments],
    [QimetQessd] AS [installment_amount],
    [PlaceNumber1] AS [legacy_area_number_2]
FROM [EbCustomers]
"@
    },
    @{
        PgTable = "employees"
        CsvName = "employees.csv"
        Columns = @("employee_id", "phone_number", "employee_name", "governorate", "district_center", "village")
        AccessSql = @"
SELECT
    [id] AS [employee_id],
    [Phpne] AS [phone_number],
    [EmpN] AS [employee_name],
    [Mohafza] AS [governorate],
    [Markz] AS [district_center],
    [karia] AS [village]
FROM [EbEmp]
"@
    },
    @{
        PgTable = "case_statuses"
        CsvName = "case_statuses.csv"
        Columns = @("case_status_id", "case_status_name")
        AccessSql = @"
SELECT
    [id] AS [case_status_id],
    [departMent] AS [case_status_name]
FROM [EBhalat]
"@
    },
    @{
        PgTable = "company_settings"
        CsvName = "company_settings.csv"
        Columns = @(
            "company_name_ar", "general_manager_name", "email_address", "mobile_number",
            "website_url", "address", "commercial_registry_number", "tax_number",
            "image_path", "company_name_en", "civil_defense_license_number",
            "civil_defense_license_start_date", "civil_defense_license_end_date",
            "municipality_license_number", "municipality_license_start_date",
            "municipality_license_end_date"
        )
        AccessSql = @"
SELECT
    [NameNombanyar] AS [company_name_ar],
    [GENRAL-mANAGER] AS [general_manager_name],
    [EMAIL1] AS [email_address],
    [MOBILE] AS [mobile_number],
    [WEBSITE] AS [website_url],
    [ADRESS] AS [address],
    [SEGEL1] AS [commercial_registry_number],
    [TAX] AS [tax_number],
    [imagepath] AS [image_path],
    [NameNombanyEN] AS [company_name_en],
    [NumberRDefa3] AS [civil_defense_license_number],
    [Datefir1] AS [civil_defense_license_start_date],
    [Datefin1] AS [civil_defense_license_end_date],
    [NumberRbaldia3] AS [municipality_license_number],
    [Datefir2] AS [municipality_license_start_date],
    [Datefin2] AS [municipality_license_end_date]
FROM [sd]
"@
    },
    @{
        PgTable = "app_users"
        CsvName = "app_users.csv"
        Columns = @(
            "username", "password_legacy_plain_text", "can_access_statuses",
            "can_access_customers", "can_access_employees",
            "can_access_daily_followups", "can_access_reports", "can_access_users",
            "can_access_places_or_leaves", "can_access_reports_secondary",
            "can_access_notification_report", "can_access_salary_receipt",
            "can_access_end_of_service_reward", "can_access_cars",
            "can_access_users_secondary", "legacy_permission_flag_14",
            "user_role_level"
        )
        AccessSql = @"
SELECT
    [User_Name] AS [username],
    [Password] AS [password_legacy_plain_text],
    [t1] AS [can_access_statuses],
    [t2] AS [can_access_customers],
    [t3] AS [can_access_employees],
    [t4] AS [can_access_daily_followups],
    [t5] AS [can_access_reports],
    [t6] AS [can_access_users],
    [t7] AS [can_access_places_or_leaves],
    [t8] AS [can_access_reports_secondary],
    [t9] AS [can_access_notification_report],
    [t10] AS [can_access_salary_receipt],
    [t11] AS [can_access_end_of_service_reward],
    [t12] AS [can_access_cars],
    [t13] AS [can_access_users_secondary],
    [t14] AS [legacy_permission_flag_14],
    [h1] AS [user_role_level]
FROM [user]
"@
    },
    @{
        PgTable = "daily_followups"
        CsvName = "daily_followups.csv"
        Columns = @(
            "daily_followup_id", "sequence_number", "follow_up_date", "customer_id",
            "employee_id", "case_status_id", "notes", "follow_up_month",
            "follow_up_year", "legacy_month_year_code", "contact_count",
            "installment_duration_years", "remaining_installments",
            "installment_amount", "installment_type", "buyer_name",
            "buyer_phone_number", "unit_sale_amount", "seller_commission_amount",
            "buyer_commission_amount"
        )
        ReadColumns = @(
            "daily_followup_id", "sequence_number", "follow_up_date", "customer_id",
            "employee_id", "case_status_id", "notes_value", "follow_up_month",
            "follow_up_year", "legacy_month_year_code", "contact_count",
            "installment_duration_years", "remaining_installments",
            "installment_amount", "installment_type", "buyer_name",
            "buyer_phone_number", "unit_sale_amount", "seller_commission_amount",
            "buyer_commission_amount"
        )
        AccessSql = @"
SELECT
    [id] AS [daily_followup_id],
    [number] AS [sequence_number],
    [date123] AS [follow_up_date],
    [Phone_id] AS [customer_id],
    [emp_id] AS [employee_id],
    [Halat_id] AS [case_status_id],
    [Notes] AS [notes_value],
    [month123] AS [follow_up_month],
    [year123] AS [follow_up_year],
    [TMY] AS [legacy_month_year_code],
    [count25] AS [contact_count],
    [ModQessd] AS [installment_duration_years],
    [motapQessd] AS [remaining_installments],
    [QimetQessd] AS [installment_amount],
    [TypeQssd] AS [installment_type],
    [namepur] AS [buyer_name],
    [phonePur] AS [buyer_phone_number],
    [salles] AS [unit_sale_amount],
    [3molasales] AS [seller_commission_amount],
    [3molapur] AS [buyer_commission_amount]
FROM [EPYaomia]
"@
    }
)

$accessConnection = New-Object System.Data.Odbc.OdbcConnection "Driver={Microsoft Access Driver (*.mdb, *.accdb)};Dbq=$AccessPath;"
$accessConnection.Open()

try {
    foreach ($table in $tables) {
        $csvPath = Join-Path $WorkDir $table.CsvName
        $readColumns = $table.ReadColumns
        if ($null -eq $readColumns) {
            $readColumns = $table.Columns
        }
        Export-AccessQueryToCsv -Connection $accessConnection -Sql $table.AccessSql -Columns $table.Columns -ReadColumns $readColumns -CsvPath $csvPath
    }

    $missingStatusPath = Join-Path $WorkDir "missing_case_statuses.csv"
    $missingStatusColumns = @("case_status_id", "case_status_name")
    $missingStatusSql = @"
SELECT DISTINCT
    y.[Halat_id] AS [case_status_id],
    'MISSING_ACCESS_STATUS_' & CStr(y.[Halat_id]) AS [case_status_name]
FROM [EPYaomia] AS y
LEFT JOIN [EBhalat] AS h ON y.[Halat_id] = h.[id]
WHERE y.[Halat_id] IS NOT NULL AND h.[id] IS NULL
"@
    Export-AccessQueryToCsv -Connection $accessConnection -Sql $missingStatusSql -Columns $missingStatusColumns -CsvPath $missingStatusPath
}
finally {
    $accessConnection.Close()
}

Invoke-Psql @("-h", $PgHost, "-U", $PgUser, "-d", $PgDatabase, "-v", "ON_ERROR_STOP=1", "-c", "TRUNCATE TABLE daily_followups, app_users, company_settings, case_statuses, employees, customers, places RESTART IDENTITY CASCADE;")

foreach ($table in $tables) {
    if ($table.PgTable -eq "daily_followups") {
        continue
    }

    $csvPath = (Join-Path $WorkDir $table.CsvName).Replace("\", "/")
    $columns = ($table.Columns -join ", ")
    Invoke-Psql @("-h", $PgHost, "-U", $PgUser, "-d", $PgDatabase, "-v", "ON_ERROR_STOP=1", "-c", "\copy public.$($table.PgTable) ($columns) FROM '$csvPath' WITH (FORMAT csv, HEADER true, NULL '\N', ENCODING 'UTF8');")

    if ($table.PgTable -eq "case_statuses") {
        $missingPath = $missingStatusPath.Replace("\", "/")
        Invoke-Psql @("-h", $PgHost, "-U", $PgUser, "-d", $PgDatabase, "-v", "ON_ERROR_STOP=1", "-c", "\copy public.case_statuses (case_status_id, case_status_name) FROM '$missingPath' WITH (FORMAT csv, HEADER true, NULL '\N', ENCODING 'UTF8');")
    }
}

$dailyTable = $tables | Where-Object { $_.PgTable -eq "daily_followups" } | Select-Object -First 1
$dailyCsvPath = (Join-Path $WorkDir $dailyTable.CsvName).Replace("\", "/")
$dailyColumns = ($dailyTable.Columns -join ", ")
Invoke-Psql @("-h", $PgHost, "-U", $PgUser, "-d", $PgDatabase, "-v", "ON_ERROR_STOP=1", "-c", "\copy public.daily_followups ($dailyColumns) FROM '$dailyCsvPath' WITH (FORMAT csv, HEADER true, NULL '\N', ENCODING 'UTF8');")

Invoke-Psql @("-h", $PgHost, "-U", $PgUser, "-d", $PgDatabase, "-v", "ON_ERROR_STOP=1", "-c", @"
SELECT 'places' AS table_name, COUNT(*) FROM places
UNION ALL SELECT 'customers', COUNT(*) FROM customers
UNION ALL SELECT 'employees', COUNT(*) FROM employees
UNION ALL SELECT 'case_statuses', COUNT(*) FROM case_statuses
UNION ALL SELECT 'daily_followups', COUNT(*) FROM daily_followups
UNION ALL SELECT 'company_settings', COUNT(*) FROM company_settings
UNION ALL SELECT 'app_users', COUNT(*) FROM app_users
ORDER BY table_name;
"@)
