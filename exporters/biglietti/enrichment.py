"""إثراء السجلات (سعر، كثافة، ماكينة، VMM22) وبناء صفوف الفيلاتو.

جزء من حزمة exporters.biglietti (انظر ARCHITECTURE_AR.md). الواجهة القديمة
exporters/biglietti_exporter.py تعيد تصدير كل الأسماء من هنا."""

from __future__ import annotations

from typing import Any

from calculate.raw_batch import is_customer_lot
from exporters.biglietti.fields import (
    _clean,
    _cliente_med,
    _commento_for,
    _number,
    _partita_med,
    _polmoni_extra,
)
from exporters.biglietti.loaders import _get
from exporters.biglietti.lookups import (
    _prezzo_for,
    _titolo_lookup,
    compute_delivery_date,
)
from exporters.biglietti.machines import (
    MACHINE_SIZE_TABLE_MED_EXTRA,
    _machine_for_count,
)
from exporters.biglietti.records import OrderRecord


def enrich_records(
    records: list[OrderRecord],
    customer: str,
    codes_map: dict[str, str] | None = None,
    densita_map: dict[int, dict[str, Any]] | None = None,
    vmm_ratio_map: dict[int, float] | None = None,
    price_lookup: dict[tuple, tuple] | None = None,
) -> None:
    """Fills in Titolo, Commento, M/C, KG, Densita, Color Tube, VMM22,
    Prezzo and the MED "Partita MED"/"Cliente MED" pair, in place.
    Anything whose source file was not provided is left blank, same as
    before, instead of raising.
    """
    codes_map = codes_map or {}
    densita_map = densita_map or {}
    vmm_ratio_map = vmm_ratio_map or {}
    price_lookup = price_lookup or {}

    # --- M/C: group by Bagno, sum Rocche (+ MED Polmoni bonus). EL KAMAL's
    # own source already gives a correct M/C per row, so it's left alone.
    if customer != "EL_KAMAL":
        groups: dict[str, list[OrderRecord]] = {}
        for r in records:
            groups.setdefault(r.bagno or "", []).append(r)
        for bagno, members in groups.items():
            total = sum(_number(m.quantity_cones) or 0 for m in members)
            if customer == "MED":
                total += sum(_polmoni_extra(m.additional_raw) for m in members)
            extra = MACHINE_SIZE_TABLE_MED_EXTRA if customer == "MED" else None
            machine = _machine_for_count(total, extra=extra)
            for m in members:
                m.machine = machine

    for r in records:
        # Titolo: Articoli.xlsx lookup takes priority (fuller description);
        # the raw yarn sheet's shorter Titolo is the fallback.
        r.title = _titolo_lookup(r.article, codes_map) or r.title

        # EL KAMAL's Commento (COMMENTO RIGO ORDINE) already arrives correct
        # from the source and isn't a dash-encoded comment like ELVY/MED's.
        if customer != "EL_KAMAL":
            r.commento = _commento_for(customer, r.additional_raw)

        if customer == "MED":
            r.partita_med = _partita_med(r.additional_raw)
            r.cliente_med = _cliente_med(r.additional_raw)

        try:
            batch_key = int(_number(r.raw_batch)) if _number(r.raw_batch) is not None else None
        except (TypeError, ValueError):
            batch_key = None

        if batch_key is not None and batch_key in densita_map:
            entry = densita_map[batch_key]
            peso_net = entry.get("peso_net")
            r.kg = int(round(peso_net * (_number(r.quantity_cones) or 0))) if peso_net is not None else r.raw_weight
            r.densita = entry.get("densita", "")
            r.color_tube = entry.get("color_tube", "")
        else:
            r.kg = r.raw_weight

        if batch_key is not None and batch_key in vmm_ratio_map:
            kg_per_cone = vmm_ratio_map[batch_key]
            r.vmm22 = round(kg_per_cone * (_number(r.quantity_cones) or 0), 2)

        r.prezzo = _prezzo_for(r.article, r.color_code, price_lookup)

    if customer == "ELVY":
        compute_delivery_date(records)


def _filato_rows(
    records: list["OrderRecord"],
    raw_rows: list[dict[str, Any]],
    magazino_summary=None,
) -> list[dict[str, Any]]:
    """One row per raw batch, for the post-ERP-entry (Create EXCEL+Biglietti)
    stage: stock availability was already checked earlier, on the Ordine
    page, before the order went into the system -- so Rocche here is simply
    the order's own total cone count for that batch, not a fresh warehouse
    lookup. Peso is still derived from Magazino, but scaled to that same
    order quantity: (warehouse weight / warehouse cones) for the batch,
    times how many cones THIS order actually needs, i.e. the total weight
    for the cones being pulled -- not the warehouse's full stock weight.
    """
    raw_by_article = {_clean(_get(r, "Articolo")).upper(): r for r in raw_rows}

    totals: dict[str, float] = {}
    for rec in records:
        # A MED customer lot is shown in Partita GG, but it is not yarn to
        # prepare: it stays in PG-X until a real batch is assigned.
        if is_customer_lot(getattr(rec, "raw_batch", ""), getattr(rec, "customer_code", "")):
            continue
        key = _clean(rec.raw_batch)
        if not key:
            continue
        totals[key] = totals.get(key, 0) + (_number(rec.quantity_cones) or 0)

    warehouse_rate = {}
    rate_by_partita = {}

    def stock_key(value: Any) -> str:
        text = _clean(value)
        number = _number(text)
        return str(int(number)) if number is not None and float(number).is_integer() else text

    if magazino_summary is not None:
        for row in magazino_summary.itertuples(index=False):
            article = _clean(getattr(row, "articolo", "")).upper()
            partita = stock_key(getattr(row, "partita", ""))
            if not article or not partita:
                continue
            try:
                mag_rocche = float(getattr(row, "mag_rocche", 0) or 0)
                mag_peso = float(getattr(row, "mag_peso", 0) or 0)
            except (TypeError, ValueError):
                continue
            if mag_rocche <= 0:
                continue
            rate = mag_peso / mag_rocche
            warehouse_rate[(article, partita)] = rate
            rate_by_partita.setdefault(partita, set()).add((article, rate))

    out = []
    seen: set[str] = set()
    for rec in records:
        if is_customer_lot(getattr(rec, "raw_batch", ""), getattr(rec, "customer_code", "")):
            continue
        key = _clean(rec.raw_batch)
        if not key or key in seen:
            continue
        seen.add(key)
        article_g = ("G" + rec.article[1:]) if rec.article[:1].upper() == "C" else rec.article
        raw = raw_by_article.get(article_g.upper(), {})
        stock_partita = stock_key(key)
        order_rocche = totals[key]
        per_cone_rate = warehouse_rate.get((article_g.upper(), stock_partita))
        if per_cone_rate is None:
            # Some ERP exports contain a visually similar article code, e.g.
            # G1300275 in the order and G130027S in Magazino.  A Partita is
            # unique in the stock export, so use it only when it has one
            # unambiguous warehouse article.
            partita_matches = rate_by_partita.get(stock_partita, set())
            if len(partita_matches) == 1:
                per_cone_rate = next(iter(partita_matches))[1]
        peso = round(per_cone_rate * order_rocche, 2) if per_cone_rate is not None else _number(_get(raw, "وزن", "Peso"))
        out.append({
            "Articolo": article_g,
            "Titolo": rec.title or _clean(_get(raw, "Titolo")),
            "Partita": key,
            "Rocche": order_rocche,
            "Peso": peso,
            "تحضير خام": _clean(_get(raw, "Custom", "تحضير خام")) or "تحضير خام",
        })
    return out
