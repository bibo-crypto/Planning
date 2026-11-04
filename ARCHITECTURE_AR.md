# هيكل برنامج Planning (دليل سريع بالعربي)

الصور: `docs/architecture_overview.png` (الطبقات) و`docs/architecture_modules.png` (كل ملف ومسؤوليته).
لإعادة رسمها بعد أي تغيير: عدّل الجداول داخل `docs/make_architecture_png.py` ثم شغّله.

## الفكرة في سطر
ملف مدخل (PDF / Excel) ← **parsers** يقرأه ← **pipelines** ترتّب الخطوات باستخدام **calculate** (القواعد) ← **exporters** تكتب Excel / Word ← **gui** تعرض كل ذلك للمستخدم، و**utility** تخزّن وتشترك فيها كل الأجزاء.

## الطبقات
| المجلد | مسؤوليته | قاعدة |
|---|---|---|
| `gui/` | النافذة والصفحات والأزرار | الوحيدة التي تستورد Tk. لا تضع قاعدة عمل فيها |
| `pipelines/` | خطوات التحويل: اقرأ ← احسب ← جهّز الصفوف | لا تستورد `gui` |
| `parsers/` | تحويل PDF / Excel إلى بيانات | لا تستورد `gui` |
| `calculate/` | قواعد العمل الصرفة (Bagno، Abbina، الأسعار...) | لا تستورد `gui` |
| `exporters/` | كتابة ملفات Excel / Word | لا تستورد `gui` |
| `utility/` | SQLite والكاش والمسارات والنسخ الاحتياطي والتحديث | لا تستورد `gui` |

القاعدة الوحيدة المفروضة بالاختبار (`tests/test_architecture_rules.py`): **لا أحد يستورد `gui` غير `gui` نفسه**.

استثناءات معروفة للاتجاه (من الأعلى للأسفل) وما زالت موجودة، وتحتاج تنظيفاً لاحقاً:
- `calculate/prezzi.py` يستدعي `exporters.biglietti_exporter` (استيراد داخل الدالة).
- `exporters/excel_exporter.py` و`column_catalog.py` يستوردان من `pipelines`.
- `utility/source_hub.py` يستورد من `exporters` و`parsers`.

## حزمة Biglietti (`exporters/biglietti/`)
كانت ملفاً واحداً بـ 2583 سطراً (`biglietti_exporter.py`). صارت 10 وحدات، **كل وحدة تعتمد فقط على التي قبلها**:

| الوحدة | المسؤولية |
|---|---|
| `records` | `OrderRecord`: سطر أمر جاهز للطباعة |
| `fields` | دوال صغيرة تنظّف حقول الأمر (Commento / Polmoni / Dispo / أسماء الملفات) |
| `machines` | جدول أحجام الماكينات واختيار الماكينة |
| `loaders` | قراءة ERP وDispo-Bagno وEL KAMAL إلى `OrderRecord` |
| `lookups` | الأسعار والكثافة وتاريخ التسليم وMarca وVMM22 |
| `enrichment` | إثراء السجلات وبناء صفوف الفيلاتو |
| `workbook_io` | قفل الكتابة على الملفات + `style_sheet` لتنسيق الشيتات |
| `excel_writer` | إكسل العميل وملف الفيلاتو + ربط الأعمدة بالبيليتو |
| `shared_workbook` | ملف Create Orders المشترك (إضافة / تحديث / حذف / PG-X) |
| `word_writer` | بيليتو الوورد |

`exporters/biglietti_exporter.py` بقي **واجهة قديمة** تعيد تصدير نفس الأسماء بالضبط، فلا يتغير أي `import` قديم.
للكود الجديد استورد من الوحدة المختصة مباشرة.

> انتبه في الاختبارات: `monkeypatch` على اسم من الواجهة القديمة لا يؤثر على دالة انتقلت. اضبطه في الوحدة التي تستخدمه
> (مثال: `exporters.biglietti.lookups._PREZZO_LOOKUP_CACHE`).

## أين أضيف كذا؟
- عمود جديد في ملف إخراج: في جدول الأعمدة داخل المصدّر المختص، وسيظهر تلقائياً في نافذة Columns (`exporters/column_catalog.py`).
- قاعدة سعر / Bagno / Abbina: في `calculate/` (لا في `gui/`).
- صفحة جديدة: ملف في `gui/tabs/` يستدعي pipeline، وتسجّلها في `gui/gui.py`.
- حقل جديد في بيليتو الوورد: `TICKET_CELL_COLUMNS` في `excel_writer` ثم الخلية في `word_writer`.

## النسخ الاحتياطي والبيانات
`utility/backup.py`: نسخة تلقائية يومياً عند التشغيل في `backups/` تحتفظ بآخر 10 أيام، وزر Restore يفتح على هذا المجلد.
`settings/` و`cache/` و`logs/` و`backups/` وقواعد `*.sqlite3` بيانات تشغيل ولا تُرفع للريبو ولا تدخل الـ installer.
