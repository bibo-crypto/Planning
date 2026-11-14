# تقرير الفحص الهندسي — مشروع Planning (commit `eec23af`، 12 نوفمبر 2026)

> **قاعدة التقرير:** أي رقم هنا اتنفذ فعلًا وأي حاجة ماتجرّبتش مكتوب جنبها **NOT VERIFIED**.
> البيئة اللي اتنفذ فيها الفحص: Linux + شاشة افتراضية 1920×1080. ده **مش** ويندوز.

## 1. الملخص التنفيذي
- **سبب فشل الـ job الأخير اتأكد بالتجربة:** خطوة `Annotate the failed tests` بترجّع exit code 1 على أي run أخضر (تفاصيل في 2). الاختبارات نفسها سليمة (666 و667 passed).
- **اتصلّح في الـ workflow فقط** (`.github/workflows/tests.yml`)، من غير أي تعديل في كود التطبيق أو الاختبارات.
- بعد الإصلاح: الـ suite الكاملة **668 passed / 0 failed على Python 3.12.3 وعلى 3.14.10** (Linux).
- **مشكلة تعليق النسخة المنشورة على "Loading application pages" لسه مش متحدد سببها.** اتشحنت أدوات تشخيص (انظر 7)، ومحتاجة تأكيد على جهازك.
- **اكتشاف مهم جديد:** أرقام الـ release tags (v1.2.x) منفصلة تمامًا عن `version.txt` (1.0.2)، والـ updater بيقارن بينهم (High — انظر 9).

## 2. السبب الجذري لفشل الـ CI الأخير
**الدليل:** الـ logs الحقيقية (`pytest-log-py3.12.zip` و`py3.14.zip`) تقول `666 passed, 2 skipped` و`667 passed, 1 skipped` ومفيش أي سطر `FAILED/ERROR`. الاختبارات نجحت، ومع ذلك الـ job أحمر.

**السبب:** GitHub بيشغّل `shell: bash` بـ `bash -eo pipefail`. في الخطوة:
```
failed=$(grep -E '^(FAILED|ERROR) ' pytest.log | head -25 | ... | awk ...)
```
`grep` بيرجّع 1 لما ما يلاقيش حاجة (وهو الوضع الطبيعي في run أخضر). مع `pipefail` الـ pipeline كله بيرجّع 1، وأمر الإسناد `failed=$(...)` بيفشل، و`-e` بيوقف الـ step، فالـ job يتعلّم فاشل.

**التحقق (اتنفذ فعلًا):** شغّلت الـ step الفعلي من الـ YAML بنفس أمر GitHub (`bash --noprofile --norc -eo pipefail`) على الـ log الأخضر الحقيقي:

| السيناريو | الـ step القديم | الـ step الجديد |
|---|---|---|
| log أخضر حقيقي (666 passed) | **exit 1** | exit 0 |
| log فيه فشل (3 failed) | 0 | 0 (والـ error annotation بيتكتب) |
| log فيه 60 فشل | 0 | 0 |
| log من غير سطر summary (انهيار) | **exit 1** | exit 0 |

الخطوة دي كانت موجودة من commit `5260563` (قبل أي تعديل منّي)، وماظهرتش قبل كده لأن كل الـ runs السابقة كان فيها فشل فعلي.
الـ step `Show the result on the run summary` فيه نفس العيب الكامن (بيفشل لو الـ log من غير summary)، واتصلّح بنفس الطريقة.

**تصحيح لتحليل قلته قبل كده:** كنت رجّحت إن الـ "exit code 1" جاي من خطوة رفع دقة الشاشة. ده كان غلط. الدليل بيقول إنه خطوة `Annotate`.

**تأكيد إن الإصلاح مش بيخبّي فشل حقيقي:** الـ job بيفشل من خطوة `Run the test suite` نفسها (`set -o pipefail` + `tee`). جرّبت: أمر بيرجّع 1 عبر نفس الـ pipeline = exit 1.

## 3. الفشل التاريخي وحالته الحالية
**قيد مهم:** الـ GitHub API رجّع rate-limit، فما قدرتش أقرا logs الـ runs القديمة. عندي بس: لقطتين من الـ Actions اللي بعتّهم، والـ logs الأخيرة، وتاريخ git. أي استنتاج عن الـ runs القديمة معلَّم.

| الاختبار | النوع | الدليل | الحالة |
|---|---|---|---|
| `test_machine_timeline_layout` (2 اختبار)، `test_overview_tables` (1) | **بيئة**: دقة شاشة الـ runner | run #6: القيم `77 > 77` و`1026 >= 1100`. ويندوز بيقص النافذة على عرض الشاشة (~1024) | الفشل اختفى بعد `007bd51` (تخطي بسبب واضح + خطوة رفع الدقة). **غير معروف** هل بيعدّوا أو بيتخطّوا في CI (الـ log القديم ماكانش فيه `-rs`) |
| `test_sync_venv_packages` | **افتراض خاطئ في الاختبار** | الاختبار القديم كان فاكر إن `sys_platform == "win32"` معناه "مش على الجهاز ده"، فكان بيفشل على ويندوز | اتصلّح في `db3b44c` (اختبار مرتبط بـ `sys.platform` الفعلي). ومعدّي دلوقتي |
| `test_git_publisher`، `test_publish_script` | **بيئة**: إعدادات git/ترميز/home الحقيقية للجهاز | `db3b44c` أضاف `conftest.py` (عزل HOME وgit config) وترميز UTF-8 في `tests/git_helpers.py` | معدّيين. جرّبتهم هنا في بيئة git نضيفة (من غير identity أو config): **56 passed** |

**مقارنة الأعداد:** run #6 = 642 passed + 3 failed + 2 skipped = 647. دلوقتي 666 + 2 = 668 = 647 + 21 اختبار جديد. مفيش اختبار اتحذف.

**مشكلة لسه مفتوحة (Medium):** الـ 2 skipped على 3.12 مقابل 1 على 3.14. السبب غير معروف لأن الـ log مفيهوش أسباب التخطي. أول اختبار اتخطّى في run الجهاز عندك (`s` في الموضع 24) هو على الأرجح `test_failed_validation_never_closes_notifications`، والـ fixture بتاعه `tk_root` بيحوّل أي `TclError` إلى skip. يعني ده تخطي ممكن يخبّي مشكلة Tk حقيقية. الإصلاح الجزئي المضاف: `-rs` في الـ workflow، فالسبب هيظهر في الـ run الجاي.

## 4. نتائج SQLite وسلامة البيانات
**اتأكد بالاختبار:** DB جديدة بتتكوّن كاملة؛ DB قديمة (أعمدة ناقصة) بتترقّى من غير ضياع سجل؛ الترقية مرتين مش بتغيّر حاجة؛ ملف تالف بيرمي خطأ ويفضل زي ما هو؛ البيانات بتفضل بعد restart بعمليات منفصلة؛ مفيش تكرار بعد 4 تشغيلات؛ مفيش lock أو transaction مفتوح بعد التشغيل (`integrity_check = ok` و WAL).

| # | الأولوية | الملاحظة | الحالة |
|---|---|---|---|
| F1 | High | `init_db()` كان بيبلع أي `OperationalError` في الـ 7 ALTER | **اتصلّح** |
| F2 | Medium | فشل snapshot النسخ الاحتياطي بيرجع لنسخ الملف الخام من غير log، و`daily_backup` بيبلع الأخطاء | **اتصلّح** (log) |
| F3 | Medium | `prezzi_db` بيحوّل أي خطأ لـ "مفيش cache" من غير log | **اتصلّح** (log) |
| F6 | Medium | **دليل حقيقي من log جهازك:** `disk I/O error` مرتين يوم 19 أكتوبر (`SQLite startup restore failed` و`Could not persist DFM snapshot`) | أضفت retry (3 محاولات) للأخطاء المؤقتة فقط (locked / disk I/O). السبب الجذري على جهازك **غير معروف** |
| F4 | Low | مفيش `PRAGMA user_version` | مفتوح (اختياري) |
| F5 | Low | `restore_backup` مش atomic لو فشل في النص | مفتوح (يحتاج قرارك لأنه بيغيّر سلوك الـ restore) |

**سليم:** كل اتصال بيتقفل (فحص AST: 0 دوال بتفتح أكتر مما بتقفل). الـ indexes موجودة على أعمدة البحث. WAL وbusy_timeout متظبطين. حذف ملفات `-wal`/`-shm` قبل الاستعادة وحماية path traversal موجودين.
**لم يُراجع بعمق (NOT VERIFIED):** الوصول المتزامن من threads متعددة تحت حمل، وanalysis كامل لـ `orders_db`.

## 5. الأداء وسرعة بدء التشغيل
**القياس هنا** (Linux، بيانات اصطناعية بحجم بياناتك من الـ log):
- بدء التطبيق من profile فاضي: **~0.8 ثانية** (1.12 ثانية تحت cProfile). بناء الصفحات `_build_ui` حوالي 0.15 ثانية. أغلب الباقي استيراد وحدات التابات.
- استعادة ما بعد الـ restart (fresh process): DFM 23,986 صف = 0.43 ث، Listini 27,152 = 0.18 ث، الباقي أقل من 0.1 ث لكل واحد. **الإجمالي ~0.75 ثانية**. حجم الـ DB حوالي 18 MB.
- `init_db()` أول استدعاء 34 مللي ثانية، والاستدعاءات التالية 0.48 مللي ثانية. استدعاءه من 5 أماكن مش مشكلة.
- الـ lazy loading موجود (استيراد الوحدات الثقيلة عند الاستخدام).

**NOT VERIFIED:** القياس على جهازك الحقيقي أو الـ exe المبني (ومعاه الـ antivirus)، واستهلاك الذاكرة. الأرقام دي مش بتفسّر التعليق. لا يوجد bottleneck واضح في SQLite أو في بناء الصفحات.

## 6. العمارة وجودة الكود
- **ملفات ضخمة:** `gui/gui.py` (~80 KB)، `overview_tab.py` (~64 KB)، `situazione_tab.py` (777 سطر). مفيش تقسيم موصى به بدون سبب مُثبت.
- **`except Exception` بكثرة:** حوالي 248 موضع (gui 160، utility 42، parsers 14، exporters 13، pipelines 12، calculate 7). كل موضع يحتاج مراجعة: هل الخطأ متوقع؟ وهل بيتسجل؟ (الـ F1-F3 جزء من الموضوع ده.)
- **ruff (E9,F) على الكود غير الاختبارات:** 23 ملاحظة.
  - 12 × `F821` في `gui/tabs/kamal_tab.py` هي **false positives**. الأسماء بتتحمّل lazy عن قصد (`globals()[_name] = lazy_call(...)`) في السطور 27-40. ده بيعمي الأدوات الثابتة. التوصية: تعريفات صريحة تحت `if TYPE_CHECKING:`.
  - 5 × `F401` و5 × `F841`: تنظيف بسيط.
  - 1 × `F811` حقيقية في `test_startup.py` (الجذر): `import main` ثم `def main()` بنفس الاسم. السكريبت ده مش بيتجمع في pytest.
- **الـ logging:** ممتاز نسبيًا. نقطة ضعف واحدة كانت: ماكانش في أي أثر لبدء تشغيل فاشل (اتعالجت).

## 7. ملفات الـ Windows executable
- `main.spec`: onedir، `console=False`، الأيقونة و`version.txt` و`prezzi_category_map.json` متضمنين، واختبارات pandas/numpy مستبعدة. سليم.
- بيانات المستخدم في الـ exe المجمّد تروح لـ `%LOCALAPPDATA%\Planning` (مش فولدر التثبيت). مظبوط. و`PLANNING_DATA_DIR` بيتجاهله الـ exe عن قصد.
- **الـ smoke test** (`ci/smoke_exe.py` + `windows-exe.yml`) بيشغّل الـ exe على profile فاضي ثم يعيد تشغيله على نفس الـ profile ويقفله. حسب كلامك، نجح للـ commit `eec23af`. **أنا ما شغّلتهوش** (Linux) وده NOT VERIFIED من جهتي.
- **ثغرة:** الـ smoke مش بيجرّب **ترقية** profile قديم (schema قديم، بيانات حقيقية). ده السيناريو اللي فيه التعليق عندك.
- **الاعتماديات مش pinned:** `pandas>=2.0,<3` و`numpy>=1.24,<2.5` و`pyinstaller>=6,<7`. الـ build مش بالضرورة قابل للتكرار.
- **أدوات تشخيص مضافة:** `startup_hang.log` (يتكتب أوتوماتيك لو الشاشة علقت أكتر من 25 ثانية)، وسطر `Planning vX starting` أول التشغيل، وعرض رسالة خطأ بدل التعليق الصامت.
- **ملاحظة من log جهازك:** في أكتوبر الـ exe المثبّت (تحت فولدر التثبيت القديم بالاسم القديم للمنتج، مجلد `_internal\data`) كان ناقصه `prezzi_category_map.json` (اتسجل ERROR). الـ spec الحالي بيضمّنه والـ CI بيتحقق منه.

## 8. اختبارات ناقصة أو ضعيفة
**Coverage الحالي (Linux):** سطور 71.0% / branches 51.5%.

| الوحدة | سطور % | ملاحظة |
|---|---|---|
| `calculate/prezzi.py` | 88.6 | جيد |
| `utility/situazione_db.py` | 91.1 | جيد |
| `utility/backup.py` | 93.8 | جيد |
| `pipelines/ordine_med.py` | 80.5 | مقبول |
| `utility/updater.py` | 66.1 | **ضعيف** |
| `utility/source_hub.py` | 48.7 | ضعيف |
| `calculate/abbina_suggestions.py` | 26.6 | **منطق أعمال ضعيف التغطية** |
| `parsers/elvy_invoice_parser.py` | 29.1 | منطق أعمال |
| `parsers/kamal_parser.py` | 32.7 | منطق أعمال |
| `gui/tabs/shared_orders_window.py` | 3.8 | UI |
| `gui/tabs/situazione_tab.py` | 33.9 | UI كبير |
| `gui/tabs/weekly_machine_plan_tab.py` | 0 | UI |

**نقاط ضعف الاختبارات:**
- اختبارات الـ layout بتعتمد على دقة شاشة الجهاز (المعالجة الحالية: skip بسبب معلن).
- الـ fixtures `tk_root` بتحوّل `TclError` لـ skip.
- مفيش اختبار يجرّب updater end-to-end (المقارنة tag ↔ version).
- مفيش smoke لترقية profile قديم على الـ exe.

## 9. قائمة الأولويات
**Critical (مفيش مؤكد في الكود)**
- تعليق النسخة المنشورة على "Loading application pages": **السبب غير مؤكد**. (الأدلة المرجّحة: خطأ في `_build_ui` كان مبلوع، ومنها `disk I/O error` من log جهازك.)

**High**
1. **tag ↔ version.txt**: التاجات v1.1.x/v1.2.x فيها `version.txt` من 1.0.2 لـ 1.1.11، و`v1.2.3` فيه `1.0.2` (نزل من 1.1.6 في `v1.2.2`). الـ updater (`updater.py:118`) بيقارن اسم الـ tag بـ `version.txt` المثبّت. النتيجة المتوقعة: التطبيق 1.0.2 هيشوف `v1.2.3` أحدث دايمًا، حتى بعد تثبيته. **NOT VERIFIED على جهازك.** الإصلاح يحتاج قرارك في نظام الترقيم.
2. مراجعة `except Exception` (248 موضع) بالأولوية: pipelines/calculate/utility قبل gui.

**Medium**
- تخطي اختبارات `tk_root` بدل الفشل (ويخبّي TclError).
- تغطية ضعيفة لمنطق الأعمال: `abbina_suggestions`، `elvy_invoice_parser`، `kamal_parser`، `updater`.
- ruff مش في الـ CI.
- smoke لترقية profile قديم.
- pin الاعتماديات لبناء الـ release.
- F4 وF5.

**Low**
- `FutureWarning` في `parsers/situazione_loaders.py:61`.
- `test_startup.py` (الجذر): تسمية مضللة + `F811`.
- 5 `F401` و5 `F841`.

## 10. الملفات المطلوب تعديلها (بعد موافقتك) والاختبارات
| المشكلة | الملفات | اختبار التحقق |
|---|---|---|
| H1 ترقيم الإصدارات | `version.txt`، `installer.iss`، `utility/updater.py` (`DEFAULT_APP_VERSION`)، `tests/test_version_consistency.py`، ومسار النشر `publish.py` | اختبار بيتأكد إن tag الـ release = `version.txt` داخل الحزمة، واختبار `is_newer_version` مع tag مساوٍ للمثبّت |
| `tk_root` skip | `tests/test_category_integration.py` (+ الـ fixtures المشابهة) | الـ fixture تفشل لو في `DISPLAY`/ويندوز وTk بيرمي خطأ، وتتخطى بس لو مفيش شاشة فعلًا |
| تغطية منطق الأعمال | اختبارات جديدة لـ `abbina_suggestions`، `kamal_parser`، `elvy_invoice_parser` | PDF/Excel حقيقية صغيرة، وحالات فاضية/تالفة/مكررة |
| ruff في CI | `.github/workflows/tests.yml`، `gui/tabs/kamal_tab.py` (TYPE_CHECKING) | `ruff check --select E9,F` بدون فشل |
| smoke ترقية | `ci/smoke_exe.py`، `windows-exe.yml` | تشغيل exe على DB قديمة مزروعة ببيانات |
| pin الاعتماديات | `requirements.txt` + ملف constraints | بناء مرتين بنفس النتيجة |
| F4/F5 | `utility/situazione_db.py`، `utility/backup.py` | اختبار restore بفشل في النص |

## 11. ما اتغيّر في هذه الجولة (workflow فقط)
- **ملف واحد:** `.github/workflows/tests.yml` (+11 / −5).
  1. `Annotate the failed tests`: `|| true` على كل pipeline + إزالة `\r` + annotation للتخطّي.
  2. `Show the result on the run summary`: نفس التحصين + عرض سطور `SKIPPED`.
  3. أمر pytest: `-rfE` ← `-rfEs` (أسباب التخطي تظهر في الـ log).
- **لم يُعدَّل:** كود التطبيق، الاختبارات، `windows-exe.yml`.

## 12. نتائج التنفيذ الفعلية
| الفحص | النتيجة | البيئة |
|---|---|---|
| الـ suite كاملة، Python 3.12.3 (pandas 2.3.3، numpy 2.4.6) | **668 passed، 0 failed، 0 skipped، 1 warning** | Linux + Xvfb 1920×1080 |
| الـ suite كاملة، Python 3.14.10 (نفس المكتبات) | **668 passed، 0 failed، 0 skipped، 1 warning** | Linux + Xvfb 1920×1080 |
| الـ step المعدَّل على 5 سيناريوهات log | exit 0 في كلها؛ والقديم exit 1 على الأخضر | bash -eo pipefail |
| بناء الـ exe + smoke على ويندوز | **NOT VERIFIED (لم أشغّله)**. حسب كلامك نجح على `eec23af` | يحتاج push لتشغيله على runner |
| الـ 3 اختبارات layout على ويندوز | **NOT VERIFIED** | يظهر في الـ run الجاي بسبب `-rs` |

## 13. تقييم صادق
- **قاعدة الاختبارات قوية:** 668 اختبار، ونسبة الفشل صفر، والـ CI الأخضر الحقيقي ممكن بعد الإصلاح.
- **السلامة الحقيقية للإنتاج** لسه معلّقة على نقطتين: (1) تأكيد سبب التعليق على جهازك، (2) قرار ترقيم الإصدارات.
- مفيش حاجة هنا اتغيّرت في منطق الأعمال أو قواعد البيانات في هذه الجولة غير اللي اتوثّق.
