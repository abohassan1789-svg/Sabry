# حالة المشروع — 2026-08-13

> ملف حالة جديد أُنشئ بتاريخ اليوم. من الآن فصاعدًا يُنشأ ملف جديد بهذا الشكل
> (`PROJECT_STATE_YYYY-MM-DD.md`) لكل تغيير/مهمة جديدة، مع الاحتفاظ بالملفات
> السابقة كسجل تاريخي.

## معلومات عامة

- المجلد الرئيسي للتطبيق: `D:\PicoFarm\CRM_PYTHON_APP_STRUCTURE`
- نقطة التشغيل: `app/main.py` ← `app/ui/review_window.py:run_app()`
- قاعدة البيانات: PostgreSQL (`InvPhase2`)
- الملف التاريخي السابق للحالة: `PROJECT_STATE.md` (آخر تحديث 2026-07-27)

## الحالة الحالية (نقطة البداية)

- آخر مرحلة موثّقة في `PROJECT_STATE.md`:
  - **Automatic Schema Bootstrap + Installer v4.4.9** (تطبيق المخطط تلقائيًا بدون
    خطوة ترحيل يدوية).
  - نتيجة آخر تشغيل كامل للاختبارات: **1085 passed, 10 skipped, 3 failed**
    (الإخفاقات الثلاثة غير مرتبطة بالتغييرات الأخيرة).

## المهمة: إعادة تصميم شاشة العملاء (النموذج ٧)

**الوصف:** تبسيط شاشة العملاء إلى ٥ حقول + كروت مؤشرات علوية + زر بحث.

### القرارات المعتمدة
- الحقول الظاهرة: كود العميل (تلقائي، يُعرض `CUS-<id>`), اسم العميل, الهاتف,
  العنوان, رصيد أول المدة.
- كود `CUS-1001`: **عرض فقط** — الرقم الأساسي يظل عددًا صحيحًا (1001) فلا يتأثر أي
  ربط (المتابعات/الفواتير...). يبدأ من 1001 ويزيد ١ كل مرة.
- الحقول القديمة (المنطقة/المبنى/الوحدة/الدور/الضريبي/السجل...) : **مخفية من
  الشاشة** لكنها باقية في قاعدة البيانات (`hidden_on_form=True`) بلا فقد بيانات.
- الكروت العلوية: **عدد العملاء** + **أعلى عميل مبيعات**.
- مصدر مبيعات كارت "أعلى عميل": جدول `sales_invoices` (المعتمدة فقط،
  `total_including_vat`).

### الملفات المتأثرة
- `app/database/migrations/019_add_customer_opening_balance.sql` (+ downgrade):
  عمود `opening_balance numeric(18,2) NOT NULL DEFAULT 0`.
- `app/database/schema/full_schema.sql`: `ALTER TABLE customers ADD COLUMN IF NOT
  EXISTS opening_balance ...` (يُطبَّق تلقائيًا عند الإقلاع عبر `ensure_full_schema`).
- `app/services/review_data_service.py`: تعديل `TABLE_SPECS["customers"]` (الحقول
  الظاهرة/المخفية، `list_columns`، `search_columns`)؛ إضافة `count_customers()` و
  `top_customer_by_sales()`؛ حارس حفظ يحوّل رصيد فارغ إلى 0.
- `app/ui/common/theme.py`: `opening_balance` ضمن الحقول المحاذاة يمين.
- `app/ui/screens/base_crud_screen.py`: خُطّاف عرض `_display_value(field, value)`
  يُستخدم في الجدول والنموذج ومعاينة الكود الجديد (بدون تغيير القيمة المخزّنة).
- `app/ui/screens/customers_screen.py`: `FORM_COLUMNS=1`، تنسيق `CUS-`، الكروت
  العلوية + تحديثها، زر «بحث» (أيقونة) يفتح `CustomerLookupDialog` ويحمّل العميل
  في النموذج للتعديل، تعبئة الرصيد `0.00` عند سجل جديد.
- اختبارات مُحدّثة/مضافة: `test_review_data_service.py`, `test_excel_io_service.py`,
  `test_customers_whatsapp.py`.

## التحقق

- `py_compile` للملفات المعدّلة: **OK**.
- الحزم المستهدفة (عملاء/إكسل/بحث/صلاحيات...): **104 passed**.
- كامل `tests/unit`: **770 passed, 1 skipped, 3 failed** — والإخفاقات الثلاثة
  موجودة مسبقًا وغير مرتبطة (اختبارا debounce في تقرير المتابعة الذكي +
  `test_skeleton_imports_settings` يتوقع `CRM` بينما الاسم الحالي `picoFdb`).
- اختبار دخان headless (offscreen): الكود يظهر `CUS-1001` والـ UserRole يظل
  `1001`؛ الكروت: 128 / محمد أحمد / 45,200.00؛ الحقول الخمسة فقط؛ زر البحث موجود.

## تعديلات لاحقة على شاشة العملاء (نفس اليوم)

- إخفاء زرّي **WhatsApp** و**المرفقات** من نموذج العميل (`setVisible(False)` مع
  الإبقاء على الكائنات/المنطق) — `customers_screen.py`.
- الجدول يعرض **اسم العميل + الهاتف فقط** (`list_columns=("customer_name",
  "phone_number")`)؛ كود العميل (`customer_id`) لا يزال يُجلب لكل صف للاختيار/
  التحميل — `review_data_service.py`.
- اختبارات مضافة: `test_whatsapp_and_attachments_buttons_are_hidden`,
  `test_customer_grid_shows_only_name_and_phone`.

## المهمة: تفعيل زر «اعتماد فاتورة المبيعات» (بدون ربط بالمرحلة الثانية)

اعتماد **محلي فقط**: يحوّل المسودة إلى `approved` ويضبط `approved_at`/`approved_by`
ويسجّل قيد تدقيق (`action=approve`) — **بدون أي استدعاء ZATCA / بيانات المرحلة
الثانية**.

- `app/services/saudi_sales_invoice_service.py`: `is_approval_available()` → `True`؛
  `approve(invoice_id, expected_row_version, *, user_id)` (صلاحية `approve` +
  رفض غير المسودة + قيد تدقيق + تزامن متفائل).
- `app/repositories/saudi_sales_invoice_repository.py`: `approve_invoice(...)`
  (UPDATE محمي بـ `row_version` و`document_status='draft'`، بدون كتابة ZATCA).
- `app/ui/screens/saudi_sales_invoice_page.py`: `on_approve` يطلب تأكيدًا ثم يعتمد
  ويعيد التحميل؛ تلميح الزر أصبح "الاعتماد متاح للمسودة المحفوظة فقط".
- اختبارات: خدمة الاعتماد المحلي/رفض غير المسودة/الصلاحية/التزامن + اختبار شاشة
  `test_on_approve_approves_the_loaded_draft` + تحديث اختبار التلميح.

**التحقق:** `tests/services/test_saudi_sales_invoice_service.py` +
`tests/unit/test_saudi_sales_invoice_page.py` = **135 passed**. كامل `tests/unit`
= **774 passed, 2 failed** (الإخفاقان موجودان مسبقًا: اختبار debounce في تقرير
المتابعة + `test_skeleton_imports_settings`). لا انحدار من هذا العمل.

## المهمة: شاشة + جدول الموردين (النموذج ١) — نُفِّذت على مراحل

شاشة موردين جديدة بأربع حقول، نفس هيدر وأزرار العملاء، RTL، وجدول أسفلها يعرض
**اسم المورد + الموبايل** فقط. التصميم = النموذج ١ (شريط أفقي والكود شارة خضراء).

- الحقول: كود المورد (تلقائي **يبدأ 1001** ثم 1002, 1003 — بدون بادئة)، اسم المورد،
  الموبايل، رصيد أول المدة.
- قاعدة البيانات: `020_create_suppliers_schema.sql` (+ downgrade) — جدول `suppliers`
  مع Sequence تبدأ من 1001 و`DEFAULT nextval` (تخصيص آمن للتزامن، ليس MAX+1)،
  و`opening_balance numeric(18,2) NOT NULL DEFAULT 0`. وأُضيف بلوك مطابق في
  `full_schema.sql` (يُطبَّق ذاتيًا عند الإقلاع).
- الخدمة/التعريف: `TABLE_SPECS["suppliers"]`؛ `suppliers` ضمن مجموعة بدء الكود
  1001؛ وحارس الرصيد الفارغ→0 امتد ليشمل الموردين — `review_data_service.py`.
- المحاذاة: أرقام الموردين يمين — `theme.py`.
- الشاشة: `app/ui/screens/suppliers_screen.py` (`SuppliersScreen`) — يعيد استخدام
  `BaseCrudScreen` مع تخصيص جسم النموذج للشريط الأفقي + معاينة الكود 1001 وتعبئة
  الرصيد 0.00 عند "جديد".
- الربط: القائمة الجانبية (`main_window.py`: MODULES + NAV_ICONS 🚚 + PREWARM) +
  صلاحيات `crm.suppliers.*` في `permission_registry.py`.
- اختبارات: `tests/unit/test_suppliers_screen.py` (٦ حالات) + بدء الكود 1001 في
  `test_review_data_service.py`.

**التحقق:** الحزم المستهدفة **41 passed**؛ اختبار دخان offscreen: الحقول الأربعة،
الجدول عمودين (الاسم/الموبايل)، UserRole=1001، "جديد"→1001 و0.00، نفس أزرار CRUD،
RTL. كامل `tests/unit` = **779 passed, 3 failed** (نفس الإخفاقات السابقة غير
المرتبطة). بدون انحدار.

## المهمة: شاشة + جدول العمال (نفس تصميم الموردين)

شاشة عمال جديدة مطابقة لتصميم الموردين (النموذج ١) وبنفس الهيدر والأزرار، مع فرق
واحد: **كود العامل بصفر بادئ ٤ خانات** (0001, 0002, 0003 ...) — عرض فقط فوق رقم
صحيح يبدأ من 1.

- إعادة هيكلة: استُخرج الشكل المشترك في `app/ui/screens/code_band_crud_screen.py`
  (`CodeBandCrudScreen`)؛ و`SuppliersScreen`/`WorkersScreen` بقيا Thin subclasses.
- قاعدة البيانات: `021_create_workers_schema.sql` (+ downgrade) — جدول `workers`
  (Sequence تبدأ من 1، `DEFAULT nextval`، `opening_balance NOT NULL DEFAULT 0`)
  + بلوك مطابق في `full_schema.sql`.
- الخدمة/التعريف: `TABLE_SPECS["workers"]`؛ الحقول (worker_id/worker_name/mobile/
  opening_balance)؛ حارس الرصيد الفارغ→0 امتد للعمال؛ **العمال ليسوا في مجموعة بدء
  1001** فيبدأ الكود من 1 — `review_data_service.py`. المحاذاة في `theme.py`.
- الشاشة: `workers_screen.py` (`WorkersScreen`) — يرث `CodeBandCrudScreen` مع
  `_display_value` يعرض الكود `{value:04d}`.
- الربط: القائمة (`main_window.py`: MODULES + NAV_ICONS 👷 + PREWARM) + صلاحيات
  `crm.workers.*`.
- اختبارات: `tests/unit/test_workers_screen.py` (٦ حالات، تشمل تنسيق 0001/0042 وبدء
  الكود من 1).

**التحقق:** الحزم المستهدفة **35 passed** (الموردين ما زالوا يعملون بعد إعادة
الهيكلة)؛ اختبار دخان offscreen: كود العامل يظهر **0001**، الجدول عمودين، UserRole
يظل الرقم الخام، والموردون ما زالوا 1001 بدون تصفير. كامل `tests/unit` = **785
passed, 3 failed** (نفس الإخفاقات السابقة). بدون انحدار.

## المهمة: شاشة + جدول المصروفات (النموذج ١٠ — لوحة Widgets)

لوحة مصروفات تحليلية: كروت (إجمالي المصروفات + أكبر نوع) + رسمان تفاعليان (أعمدة
+ Donut حسب النوع) بجانب نموذج الإدخال، وجدول أسفلها، ونفس أزرار شاشة العمال.

- الحقول: التاريخ (يفتح على اليوم)، المبلغ، **نوع المصروف (Editable Combo يتعلّم)**،
  البيان. حقل «نوع المصروف» قائمته تُبنى من `DISTINCT` للأنواع المخزّنة، فأي نوع
  جديد تكتبه وتحفظه يظهر جاهزًا في المرة التالية (بلا جدول أنواع منفصل).
- قاعدة البيانات: `022_create_expenses_schema.sql` (+ downgrade) — جدول `expenses`
  (`id` Sequence، `expense_date date NOT NULL DEFAULT CURRENT_DATE`,
  `amount numeric(18,2) NOT NULL DEFAULT 0`, `expense_type varchar(150)`,
  `statement text`) + فهارس نوع/تاريخ + بلوك مطابق في `full_schema.sql`.
- الخدمة: `list_expense_types()` (DISTINCT)، `expenses_total()`,
  `expenses_by_type()` (GROUP BY … DESC)، `top_expense_type()` —
  `review_data_service.py`. المحاذاة في `theme.py`.
- الشاشة: `app/ui/screens/expenses_screen.py` (`ExpensesScreen`) يرث
  `BaseCrudScreen` — لوحة النموذج ١٠ (شبكة ٢×٢: إجمالي/أكبر نوع/رسم أعمدة/Donut)
  + النموذج جانبه + الجدول تحت. الرسوم من `app/ui/common/report_charts.py`
  (`DashboardBarChart`/`DashboardDonutChart` القابلة للنقر). حقل النوع Combo
  editable ذاتي التحديث؛ التاريخ يفتح على اليوم.
- الربط: القائمة (`main_window.py`: MODULES + NAV_ICONS 🧾 + PREWARM) + صلاحيات
  `crm.expenses.*`.
- اختبارات: `tests/unit/test_expenses_screen.py` (٨) + استعلامات المصروفات في
  `test_review_data_service.py` (٤).

**التحقق:** الحزم المستهدفة **35 passed**؛ اختبار دخان offscreen: الحقول الأربعة،
الجدول (تاريخ/نوع/مبلغ)، النوع Combo editable مُحمّل بالأنواع، نص حر يُقبل، الكروت
84,200.00 و«الكهرباء/21,000.00»، التاريخ = اليوم، والرسوم تُبنى بلا أخطاء. كامل
`tests/unit` = **797 passed, 2 failed** (نفس الإخفاقات السابقة). بدون انحدار.

## ملاحظات

- أعمدة/جداول المخطط (`opening_balance`, `suppliers`, `workers`, `expenses`)
  تُطبَّق ذاتيًا عند تشغيل التطبيق التالي (بوت‑ستراب المخطط)، فلا حاجة لخطوة ترحيل
  يدوية. الترحيلات 019/020/021/022 متاحة للتطبيق اليدوي إن لزم.
- «العمال» (`workers`) جدول مستقل تمامًا عن «الموظفين» (`employees`) الموجود سابقًا.
- الرسوم «تفاعلية» بمعنى قابلة للنقر (تصدر إشارة `slice_clicked`) — لم تُربط بفلترة
  بعد؛ يمكن ربط النقر بفلترة الجدول لاحقًا إن رغبت.
- رسوم المصروفات تعرض **أكبر ٥ أنواع + خانة «أخرى»** لباقي الأنواع
  (`TOP_TYPES=5`, `max_bars=TOP_TYPES+1`)؛ ونموذج الإدخال بلا سكرول (رُفع سقف
  الارتفاع 245px للمصروفات فقط).
- **بحث المصروفات عبر واجهة منبثقة:** أُلغي الجدول السفلي الظاهر (يظل مبنيًّا
  ومخفيًّا لأن تدفّق CRUD في الأساس يعتمد على `self.table`). زر «بحث» يفتح
  `app/ui/dialogs/expenses_search_dialog.py` (`ExpensesSearchDialog`): فلترة
  بين تاريخين (Checkbox + `QDateEdit`×٢) + نوع المصروف (قائمة منسدلة «الكل»+الأنواع)؛
  بدون تاريخ يعرض **آخر ٥٠٠** فقط، ومع مدة يعرض الكل (بلا حد). الاختيار (نقر مزدوج/
  Enter/زر) يحمّل المصروف في النموذج للمراجعة/التعديل. الخدمة:
  `search_expenses(date_from, date_to, expense_type, limit)`. اختبارات مضافة
  للخدمة والديالوج.
- اعتماد الفاتورة نهائي: بعده لا تعديل ولا حذف (المسودة فقط قابلة للتعديل/الحذف).
- شاشة الموردين لا تحوي أزرار إكسل (تصدير/استيراد) لأن `suppliers` غير مُضاف في
  `excel_io_service.SUPPORTED_KEYS` — يمكن إضافته لاحقًا إن طُلب.
- لم يُطبَّق أي شيء على قاعدة البيانات الحيّة في هذه الجلسة (لا يوجد وصول لقاعدة
  `picoFdb` من هنا).
- (اختياري لاحقًا) يمكن إضافة "نداء الرصيد" ككرت رقم كبير مستقل كما في تصميم
  النموذج ٧ — تُرك حاليًا لتجنّب تكرار حقل الرصيد.
