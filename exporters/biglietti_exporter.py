"""واجهة قديمة (facade): كل شيء انتقل إلى الحزمة ``exporters/biglietti/``.

هذا الملف يعيد تصدير نفس الأسماء بالضبط، فكل ``from exporters.biglietti_exporter import ...``
في البرنامج والاختبارات يستمر في العمل. الكود الجديد يفضّل الاستيراد من الوحدة المختصة:

  fields           خصائص الحقول الصغيرة          loaders          قراءة ملفات الإدخال
  lookups          الأسعار/الكثافة/التسليم        enrichment       إثراء السجلات
  machines         جدول الماكينات                excel_writer     إكسل العميل
  records          OrderRecord                   shared_workbook  ملف Create Orders المشترك
  workbook_io      قفل الكتابة + التنسيق         word_writer      بيليتو الوورد

ملاحظة للاختبارات: ``monkeypatch`` على اسم هنا لا يؤثر على الدوال التي انتقلت؛ اضبطه في الوحدة
التي تستخدمه (مثال: ``exporters.biglietti.enrichment.load_prezzo_lookup``).
"""
from __future__ import annotations

# قفل الكتابة على الملفات + تنسيق شيتات الإكسل المشترك
from exporters.biglietti.workbook_io import (  # noqa: F401
    _WORKBOOK_WRITE_LOCK,
    _serialized_workbook_write,
    _style_sheet,
    style_sheet,
)

# جدول أحجام الماكينات واختيار الماكينة حسب عدد الرُوقات
from exporters.biglietti.machines import (  # noqa: F401
    MACHINE_SIZE_TABLE,
    MACHINE_SIZE_TABLE_MED_EXTRA,
    _MACHINE_MATCH_TOLERANCE,
    _machine_for_count,
    _refresh_machine_size_table,
)

# دوال صغيرة تستخرج وتنظّف حقول الأمر (Commento / Polmoni / Dispo / أسماء الملفات)
from exporters.biglietti.fields import (  # noqa: F401
    _CLIENTE_MED_EXPANSIONS,
    _PG_PREFIX_RE,
    _PO_COMMENTO_RE,
    _clean,
    _cliente_med,
    _commento_for,
    _dispo_number,
    _dispo_suffix,
    _elvy_file_stem,
    _first_match,
    _kamal_kg,
    _key,
    _number,
    _order_number,
    _partita_med,
    _po_token,
    _polmoni_extra,
    _polmoni_segment,
    _raw_batch_from_comment,
    _segment,
    build_output_stem,
    requested_lotto_for,
    requested_lotto_from_comment,
)

# البحث في الجداول المرجعية: الأسعار، الكثافة، تاريخ التسليم، Marca/Titolo، VMM22
from exporters.biglietti.lookups import (  # noqa: F401
    PREZZO_SURCHARGE_MACHINES,
    _DELIVERY_MACHINES_LONG,
    _DELIVERY_MACHINES_MED,
    _PREZZO_LOOKUP_CACHE,
    _add_days_skip_friday,
    _compute_delivery_date,
    _load_articoli_marca_map_uncached,
    _load_densita_query_uncached,
    _load_vmm22_ratio_from_magazino_uncached,
    _prezzo_for,
    _prezzo_match_for,
    _titolo_lookup,
    apply_machine_surcharge,
    compute_delivery_date,
    load_articoli_marca_lookup,
    load_articoli_marca_map,
    load_articoli_titolo_map,
    load_densita_query,
    load_prezzo_lookup,
    load_vmm22_ratio_from_magazino,
    prezzo_for,
    prezzo_match_for,
)

# OrderRecord: سجل واحد = سطر أمر جاهز للطباعة
from exporters.biglietti.records import (  # noqa: F401
    OrderRecord,
)

# قراءة ملفات الإدخال (ERP / Dispo-Bagno / EL KAMAL) وتحويلها إلى OrderRecord
from exporters.biglietti.loaders import (  # noqa: F401
    HEADER_ALIASES,
    _DEFAULT_KAMAL_NAME,
    _ERP_DUMP_CUSTOMER_CODES,
    _get,
    _machine_number_from_dispo_code,
    _master_data_customer_name,
    _name_after_color_code,
    _read_dispo_csv,
    _read_sheet_rows,
    build_el_kamal_excel_stem,
    build_el_kamal_stem,
    detect_order_format,
    load_dispo_bagno_rows,
    load_el_kamal_order,
    load_order,
)

# إثراء السجلات (سعر، كثافة، ماكينة، VMM22) وبناء صفوف الفيلاتو
from exporters.biglietti.enrichment import (  # noqa: F401
    _filato_rows,
    enrich_records,
)

# كتابة إكسل العميل (ELVY/MED/EL_KAMAL) وملف الفيلاتو + ربط الأعمدة بالبيليتو
from exporters.biglietti.excel_writer import (  # noqa: F401
    COMMON_HEADERS,
    CUSTOMER_BY_CODE,
    EXTRA_HEADERS,
    FILATO_HEADERS,
    TICKET_CELL_COLUMNS,
    TICKET_HEADER_COLUMNS,
    customer_headers,
    export_filato_workbook,
    export_workbook,
    ticket_columns,
    ticket_hidden_labels,
)

# ملف Create Orders المشترك: إضافة/تحديث/حذف الصفوف وتاريخ التعديلات وPG-X
from exporters.biglietti.shared_workbook import (  # noqa: F401
    CREATE_EXCEL_HEADERS,
    _create_excel_row,
    _deduplicate_create_excel_rows,
    _delete_shared_rows,
    _is_pg_x,
    _partita_key,
    _record_history_before_delete,
    _sync_workbook_history,
    append_create_excel,
    deduplicate_create_excel,
    delete_pg_x_row,
    delete_shared_rows,
    delete_shipped_shared_rows,
    load_create_excel_records,
    move_pg_x_to_orders,
    pg_x_batch_stock_status,
    remove_uploaded_pgx_rows,
    save_pg_x_partita,
    sync_workbook_history,
    update_order_row,
    update_pg_x_row,
)

# كتابة بيليتو الوورد (جدول لكل لون) وسطر العنوان
from exporters.biglietti.word_writer import (  # noqa: F401
    _fill_ticket_table,
    _format_date,
    _ticket_header,
    export_word,
)
