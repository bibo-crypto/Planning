"""Draw docs/architecture_overview.png and docs/architecture_modules.png (Arabic comments).

Run:  python docs/make_architecture_png.py      (needs: matplotlib arabic-reshaper python-bidi)
Edit the LAYERS / DETAIL tables below when a module is added or its job changes.
"""
from __future__ import annotations

from pathlib import Path

import arabic_reshaper
import matplotlib
from bidi.algorithm import get_display

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

OUT = Path(__file__).parent
plt.rcParams["font.family"] = "DejaVu Sans"


def ar(text: str) -> str:
    """Arabic text shaped and reordered so matplotlib draws it correctly (right to left)."""
    return get_display(arabic_reshaper.reshape(text))


# ----------------------------------------------------------------------------- overview
LAYERS = [  # (path, Arabic title, colour, Arabic role, English module list)
    ("main.py", "نقطة الدخول", "#E2E8F0", "يجهّز اللوج ويفتح النافذة الرئيسية", ""),
    ("gui/", "الواجهة", "#DBEAFE", "كل ما يراه المستخدم: النافذة والصفحات والأزرار. لا تحتوي قواعد عمل، بل تستدعيها.",
     "gui.py · tabs/ (17 pages) · workflows/ (Elvy, Bolla, Invoice) · column_picker"),
    ("pipelines/", "خطوط المعالجة", "#DCFCE7", "ترتّب الخطوات: اقرأ ثم احسب ثم جهّز الصفوف. لكل أمر أو عميل خط.",
     "ordini_elvy · ordine_kamal · ordine_med · prezzi_elvy · create_conversion · master_import"),
    ("parsers/", "المحللات", "#FEF9C3", "تحوّل ملفات الإدخال (PDF وExcel) إلى بيانات منظمة.",
     "pdf_parser · kamal_parser · bolla_parser · elvy_invoice_parser · dfm_lookup · situazione_loaders"),
    ("calculate/", "الحسابات", "#FFEDD5", "قواعد العمل الصرفة بدون واجهة: Bagno وAbbina والأسعار والمخزن والجدول الزمني.",
     "bagno · abbina_* · prezzi · magazino · lotti · raw_batch · situazione · machine_timeline"),
    ("exporters/", "التصدير", "#FCE7F3", "يكتب ملفات الإخراج Excel وWord، والأعمدة تتبع اختيارك.",
     "excel_exporter · kamal_excel_exporter · prezzi_workbook · biglietti/ (10 modules) · input_check"),
    ("utility/", "الأدوات والتخزين", "#EDE9FE", "ما تشترك فيه كل الأجزاء: قواعد SQLite والكاش والمسارات والنسخ الاحتياطي والتحديث.",
     "situazione_db · orders_db · source_hub · path_manager · backup · column_selection · updater"),
]
DATA = [("ملفات الإدخال", "أوامر الشراء PDF وملفات ERP وListini والمخزن"),
        ("ملفات الإخراج", "إكسل ووورد (البيليتو) وملفات الـ ERP"),
        ("بيانات التشغيل", "لا تُنقل بين الأجهزة")]


def overview() -> None:
    fig, ax = plt.subplots(figsize=(15, 14))
    ax.set_xlim(0, 100); ax.set_ylim(0, 106); ax.axis("off")
    ax.text(50, 104, ar("هيكل برنامج Planning — كل طبقة ومسؤوليتها"), ha="center", fontsize=20, weight="bold")
    ax.text(50, 101.2, ar("الأسهم: الاتجاه العام للاستدعاء من الأعلى للأسفل (الاستثناءات القليلة مذكورة في ARCHITECTURE_AR.md)"), ha="center", fontsize=11, color="#475569")
    top, gap = 98.0, 2.6
    y = top
    for i, (path, title, colour, role, parts) in enumerate(LAYERS):
        h = 11.0 if parts else 7.2
        ax.add_patch(FancyBboxPatch((4, y - h), 92, h, boxstyle="round,pad=0.25,rounding_size=1.2", fc=colour, ec="#334155", lw=1.4))
        ax.text(6, y - 1.6, path, fontsize=15, weight="bold", va="top", family="DejaVu Sans Mono")
        ax.text(94, y - 1.6, ar(title), fontsize=15, weight="bold", ha="right", va="top")
        ax.text(94, y - 4.4, ar(role), fontsize=12, ha="right", va="top")
        if parts:
            ax.text(6, y - h + 1.5, parts, fontsize=10.5, ha="left", va="bottom", color="#1E293B", family="DejaVu Sans Mono")
        if i < len(LAYERS) - 1:
            ax.add_patch(FancyArrowPatch((50, y - h - 0.1), (50, y - h - gap + 0.1), arrowstyle="-|>", mutation_scale=22, color="#334155", lw=2))
        y -= h + gap
    ax.add_patch(FancyBboxPatch((4, y - 8.0), 92, 8.0, boxstyle="round,pad=0.25,rounding_size=1.2", fc="#F1F5F9", ec="#64748B", lw=1.2, ls="--"))
    for k, (t, d) in enumerate(DATA):
        cx = 82 - k * 32
        ax.text(cx, y - 1.4, ar(t), fontsize=12, weight="bold", ha="center", va="top")
        ax.text(cx, y - 4.2, ar(d), fontsize=9.5, ha="center", va="top", color="#334155")
        if k == 2:
            ax.text(cx, y - 6.2, "settings · cache · *.sqlite3 · backups", fontsize=8.5, ha="center", va="top", color="#334155", family="DejaVu Sans Mono")
    ax.set_ylim(y - 10, 106)
    fig.savefig(OUT / "architecture_overview.png", dpi=170, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ----------------------------------------------------------------------------- every module
DETAIL = {
 "main + gui/ | الواجهة": ("#DBEAFE", [
  ("main.py", "نقطة الدخول: يجهّز اللوج ويفتح النافذة"),
  ("runtime_hook.py", "يجعل مكتبات NumPy/Pandas تعمل بعد التحويل إلى exe"),
  ("gui/gui.py", "النافذة الرئيسية: تبني الصفحات وتربط المصادر والتحديث والنسخ الاحتياطي"),
  ("gui/source_bar.py", "شريط رفع ملف مصدر أعلى كل صفحة"),
  ("gui/column_picker.py", "نافذة اختيار الأعمدة وترتيبها بالسحب لملفات الإخراج"),
  ("gui/modern_widgets.py", "عناصر Tk بشكل عصري (أزرار / مفاتيح)"),
  ("gui/tree_fit.py", "يضبط عرض أعمدة الجداول حسب المحتوى"),
  ("workflows/purchase_orders.py", "صفحة Ordine Elvy: PDF أوامر الشراء إلى Excel + ملفات الـ ERP"),
  ("workflows/bolla.py", "صفحة Bolla: PDF إذن التسليم إلى Excel"),
  ("workflows/elvy_invoice.py", "صفحة فاتورة Elvy: PDF إلى Excel"),
  ("tabs/kamal_tab.py", "صفحة Ordine Kamal"),
  ("tabs/ordine_med_tab.py", "صفحة Ordine Med (+ Prezzi وFilato)"),
  ("tabs/biglietti_tab.py", "صفحة Biglietti: إكسل العميل + بيليتو الوورد + الفيلاتو"),
  ("tabs/biglietti_exports.py", "استدعاءات كسولة لدوال التصدير (تسريع الفتح)"),
  ("tabs/show_orders_tab.py", "صفحة Shared Orders: اختيار ملف Create المشترك"),
  ("tabs/shared_orders_window.py", "نافذة عرض أوامر Create (جداول وفلاتر)"),
  ("tabs/shared_order_actions.py", "إجراءات الأوامر: تعيين PG-X، حذف، طباعة بيليتو"),
  ("tabs/situazione_tab.py", "جدول Situazione الرئيسي"),
  ("tabs/situazione_refresh.py", "تحديث Situazione وإثراؤها وحفظها"),
  ("tabs/situazione_sources.py", "رفع واستعادة مصادر Situazione"),
  ("tabs/situazione_settimana_tab.py", "ملخص أسبوعي: وزن مصبوغ لكل عميل/ماكينة"),
  ("tabs/overview_tab.py", "لوحة Overview"),
  ("tabs/prezzi_tab.py", "تصفح قائمة الأسعار Listini"),
  ("tabs/magazino_filato_tab.py", "مخزن الخيوط الخام"),
  ("tabs/machine_timeline_tab.py", "الجدول الزمني للماكينات (رسم)"),
  ("tabs/weekly_machine_plan_tab.py", "خطة تشغيل الماكينات الأسبوعية"),
  ("tabs/yarn_shortage_tab.py", "ملخص نقص الخيوط"),
  ("tabs/master_data_tab.py", "البيانات المرجعية (Master Data)"),
 ]),
 "pipelines/ | خطوط المعالجة": ("#DCFCE7", [
  ("ordini_elvy.py", "يستخرج شيت Ordini ELVY من أسطر أمر الشراء ويطابق الخيط الخام"),
  ("ordine_kamal.py", "تحويل أسطر Kamal وحل أسماء الألوان"),
  ("ordine_med.py", "استخراج Ordine MED وملف Prezzi Ordine Med والفيلاتو"),
  ("prezzi_elvy.py", "ملف Prezzi-PO بجانب إكسل Ordine Elvy"),
  ("create_conversion.py", "Create: تحويل أمر عميل واحد إلى إكسل + وورد"),
  ("master_import.py", "استيراد مجلد أو ملف واحد لكل مصادر البيانات"),
 ]),
 "parsers/ | المحللات": ("#FEF9C3", [
  ("pdf_parser.py", "يقرأ PDF أوامر الشراء بالإحداثيات"),
  ("kamal_parser.py", "قراءة بيانات Kamal"),
  ("bolla_parser.py", "قراءة PDF إذن التسليم Bolla"),
  ("elvy_invoice_parser.py", "قراءة فاتورة Elvy (Invoice to Delta)"),
  ("elvy_mapping.py", "جدول مخزّن يربط أكواد Elvy بأكواد Delta"),
  ("dfm_lookup.py", "تحميل DFM.xlsx وربط الألوان"),
  ("prod_lookup.py", "بحث بيانات الإنتاج"),
  ("situazione_loaders.py", "محمّلات ملفات Situazione"),
 ]),
 "calculate/ | الحسابات": ("#FFEDD5", [
  ("bagno.py", "تسلسل First Bagno المشترك بين Elvy وKamal"),
  ("abbina_calculator.py", "تعيين Abbina تلقائياً لأسطر الأمر"),
  ("abbina_suggestions.py", "اقتراحات دمج دُفعات الصباغة"),
  ("prezzi.py", "تحميل Listini وقواعد البحث عن السعر"),
  ("magazino.py", "تحميل مخزن الخيوط الخام وتجميعه"),
  ("lotti.py", "مرجع LOTTI وقواعد تجميع Partita/Lotto"),
  ("raw_batch.py", "معنى Partita GG (لنا / لوط العميل / لا شيء)"),
  ("situazione.py", "قواعد جدول Situazione وأخطاء الأسعار"),
  ("situazione_settimana.py", "قواعد الملخص الأسبوعي"),
  ("machine_timeline.py", "بناء كتل الجدول الزمني وحساب التأخير"),
  ("order_report.py", "تقرير طلب الخيط PG-X وجدوله"),
  ("reports.py", "تقارير مبنية على حالة Situazione المحفوظة"),
  ("constants.py", "ثوابت العمل: الماكينات وسعاتها"),
 ]),
 "exporters/ | التصدير": ("#FCE7F3", [
  ("excel_exporter.py", "إكسل Ordine Elvy (Purchase Orders / Ordini ELVY / Filato)"),
  ("kamal_excel_exporter.py", "إكسل Ordine Kamal"),
  ("bolla_exporter.py", "إكسل Bolla"),
  ("elvy_invoice_exporter.py", "إكسل فاتورة Elvy"),
  ("prezzi_workbook.py", "ملف Prezzi المشترك بين Med وElvy"),
  ("column_catalog.py", "يصف الصفحات والأعمدة القابلة للاختيار والتنبيهات"),
  ("input_check.py", "يفحص ملف الإدخال قبل Convert ويذكر الأعمدة الناقصة"),
  ("biglietti_exporter.py", "واجهة قديمة تعيد تصدير حزمة biglietti/ كما كانت"),
 ]),
 "exporters/biglietti/ | حزمة Biglietti (كل وحدة تعتمد على التي قبلها فقط)": ("#FBCFE8", [
  ("records.py", "OrderRecord: سطر أمر جاهز للطباعة"),
  ("fields.py", "دوال صغيرة تنظّف حقول الأمر: Commento / Polmoni / Dispo / أسماء الملفات"),
  ("machines.py", "جدول أحجام الماكينات واختيار الماكينة حسب الرُوقات"),
  ("loaders.py", "قراءة ملفات ERP وDispo-Bagno وEL KAMAL إلى OrderRecord"),
  ("lookups.py", "البحث في الجداول المرجعية: أسعار، كثافة، تسليم، Marca، VMM22"),
  ("enrichment.py", "إثراء السجلات (سعر/كثافة/ماكينة) وصفوف الفيلاتو"),
  ("workbook_io.py", "قفل الكتابة على الملفات + تنسيق شيتات الإكسل (style_sheet)"),
  ("excel_writer.py", "إكسل العميل وملف الفيلاتو + ربط الأعمدة بالبيليتو"),
  ("shared_workbook.py", "ملف Create Orders المشترك: إضافة/تحديث/حذف + PG-X"),
  ("word_writer.py", "بيليتو الوورد: جدول لكل لون + سطر العنوان"),
 ]),
 "utility/ | الأدوات والتخزين": ("#EDE9FE", [
  ("situazione_db.py", "قاعدة dyeing_tracker.db (جداول Situazione والمصادر)"),
  ("orders_db.py", "قاعدة planning_orders (تاريخ أوامر Create)"),
  ("prezzi_db.py", "نسخة SQLite من Listini المنظّفة"),
  ("source_hub.py", "مكان واحد لرفع ومزامنة كل المصادر"),
  ("source_manager.py", "يقرأ من SQLite أولاً مع ذاكرة مؤقتة"),
  ("path_manager.py", "حفظ أماكن ملفات الإدخال المشتركة"),
  ("file_cache.py", "آخر ملف مرفوع لكل نوع (قالب عام)"),
  ("articoli_cache / densita_cache / lotti_cache / magazino_cache / prezzi_cache", "آخر ملف لكل مصدر محدد"),
  ("disk_cache.py", "كاش دائم على القرص للتحميلات الثقيلة"),
  ("master_data.py", "مخزن البيانات المرجعية المحلي"),
  ("column_selection.py", "حفظ الأعمدة المختارة وترتيبها لكل صفحة"),
  ("backup.py", "نسخ احتياطي يومي تلقائي (آخر 10 أيام) واستعادة"),
  ("notifications.py", "الإشعارات المخزّنة حسب الفئة"),
  ("excel_io.py / atomic.py", "حفظ آمن للملفات (لا يتلف عند الانقطاع) ورسائل الملف المفتوح"),
  ("ui_thread.py / window_helpers.py", "تسليم نتائج الخيوط الخلفية للواجهة بأمان / نوافذ ثانوية"),
  ("updater.py / git_publisher.py", "فحص التحديثات من GitHub / رفع التعديلات للريبو"),
  ("email_compose.py", "مسودة بريد Outlook"),
  ("utils.py", "اللوج ومسار بيانات التطبيق ودوال مشتركة"),
 ]),
}


def modules() -> None:
    row_h, head_h, pad = 1.0, 1.7, 0.8
    total = sum(head_h + len(v[1]) * row_h + pad for v in DETAIL.values()) + 4
    fig, ax = plt.subplots(figsize=(17, total * 0.43))
    ax.set_xlim(0, 100); ax.set_ylim(0, total); ax.axis("off")
    ax.text(50, total - 1.2, ar("خريطة وحدات برنامج Planning — كل ملف ومسؤوليته"), ha="center", fontsize=20, weight="bold")
    y = total - 3.6
    for title, (colour, rows) in DETAIL.items():
        h = head_h + len(rows) * row_h + 0.3
        ax.add_patch(FancyBboxPatch((1.5, y - h), 97, h, boxstyle="round,pad=0.1,rounding_size=0.5", fc=colour, ec="#334155", lw=1.2))
        en, _, arabic = title.partition(" | ")
        ax.text(3, y - 0.3, en, fontsize=13.5, weight="bold", va="top", family="DejaVu Sans Mono")
        ax.text(97.5, y - 0.3, ar(arabic), fontsize=13.5, weight="bold", ha="right", va="top")
        for k, (name, comment) in enumerate(rows):
            yy = y - head_h - k * row_h - 0.15
            ax.text(3.5, yy, name, fontsize=10.2, va="top", family="DejaVu Sans Mono", color="#0F172A")
            ax.text(97.5, yy, ar(comment), fontsize=11, ha="right", va="top", color="#1E293B")
        y -= h + pad
    fig.savefig(OUT / "architecture_modules.png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    overview()
    modules()
    print("written:", OUT / "architecture_overview.png", OUT / "architecture_modules.png")
