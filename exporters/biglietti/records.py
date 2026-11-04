"""OrderRecord: سجل واحد = سطر أمر جاهز للطباعة.

جزء من حزمة exporters.biglietti (انظر ARCHITECTURE_AR.md). الواجهة القديمة
exporters/biglietti_exporter.py تعيد تصدير كل الأسماء من هنا."""

from __future__ import annotations

from dataclasses import dataclass

from typing import Any


@dataclass
class OrderRecord:
    """One colour line of a customer order (ELVY, MED or EL KAMAL): customer, article, colour code/name, quantities, batches, delivery, bagno, price and density.
    Built by the loaders, completed by enrich_records() and consumed by the Excel and Word exporters.
    """
    customer_code: str
    customer_name: str
    article: str
    description: str
    additional_raw: str
    color_code: str
    color_name: str
    order_no: str
    order_row: str
    colored_batch: str
    raw_batch: str
    quantity_cones: float | int | None
    raw_weight: float | int | None
    dispo: str
    bagno: str
    delivery: Any = None
    machine: str = ""
    title: str = ""
    formato: str = "7777"
    commento: str = ""
    partita_med: str = ""
    cliente_med: str = ""
    kg: float | int | None = None
    densita: Any = ""
    color_tube: str = ""
    vmm22: float | int | None = None
    prezzo: Any = ""
    delivery_date: Any = ""
    print_flag: str = ""
