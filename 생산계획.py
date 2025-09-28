import argparse
import math
import tkinter as tk
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from tkinter import ttk, messagebox
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

# ───── 설정 상수 ─────
PACK_S3 = 160
PACK_S1_S2_COMBINED = 100
LOSS_SW = 20
DAYS = 30
INVENTORY_CAP = 500.0
SILO2_CAP = 300.0
NP3_MAX_INV = 350.0
LV_INIT = 100.0
LLV_INIT = 180.0
NP3_INIT_VAL = 120.0
C_MAX = 36

NP3_MIN_STOCK_BEFORE_CAMPAIGN = 50.0
NP3_TARGET_BATCH_PRODUCTION_SIZE = 320.0
NP3_CAMPAIGN_LEAD_TIME_FOR_TRIGGER = 0.1
NP3_PRODUCTION_RATE_IN_CAMPAIGN = 0.5

MINIMUM_RUN_DAYS = 3
RESERVATION_BUFFER_DAYS = MINIMUM_RUN_DAYS
S2_LV_MIN_STOCK_TRIGGER = 30.0

S1_HV_MAX_CAPA = 400.0
LLV_SAFETY_STOCK_FOR_C = 50.0


@dataclass
class RawMaterial:
    name: str
    sales_volume: float = 0.0
    inventory: float = 0.0
    production_capacity: float = 0.0

    def update(
        self,
        *,
        sales_volume: Optional[float] = None,
        inventory: Optional[float] = None,
        production_capacity: Optional[float] = None,
    ) -> None:
        if sales_volume is not None:
            self.sales_volume = sales_volume
        if inventory is not None:
            self.inventory = inventory
        if production_capacity is not None:
            self.production_capacity = production_capacity


@dataclass
class Product:
    name: str
    base_materials: List[str] = field(default_factory=list)


class InventoryManager:
    DEFAULT_MATERIALS = ("HV", "LV", "LLV", "3LV", "4LV")

    def __init__(self) -> None:
        self.raw_materials: Dict[str, RawMaterial] = {
            name: RawMaterial(name=name) for name in self.DEFAULT_MATERIALS
        }
        self.products: Dict[str, Product] = {}

    def upsert_raw_material(
        self,
        name: str,
        *,
        sales_volume: Optional[float] = None,
        inventory: Optional[float] = None,
        production_capacity: Optional[float] = None,
    ) -> RawMaterial:
        key = name.strip().upper()
        if not key:
            raise ValueError("원료 이름은 비어 있을 수 없습니다.")
        material = self.raw_materials.get(key)
        if material is None:
            material = RawMaterial(name=key)
            self.raw_materials[key] = material
        material.update(
            sales_volume=sales_volume,
            inventory=inventory,
            production_capacity=production_capacity,
        )
        return material

    def register_product(self, name: str, base_materials: Iterable[str]) -> Product:
        key = name.strip()
        if not key:
            raise ValueError("제품 이름은 비어 있을 수 없습니다.")
        normalized_materials = [m.strip().upper() for m in base_materials if m.strip()]
        self.products[key] = Product(name=key, base_materials=normalized_materials)
        for material_name in normalized_materials:
            if material_name not in self.raw_materials:
                self.raw_materials[material_name] = RawMaterial(name=material_name)
        return self.products[key]

    def material_rows(self) -> List[List[str]]:
        rows: List[List[str]] = []
        for name in sorted(self.raw_materials):
            mat = self.raw_materials[name]
            rows.append(
                [
                    mat.name,
                    f"{mat.sales_volume:.2f}",
                    f"{mat.inventory:.2f}",
                    f"{mat.production_capacity:.2f}",
                ]
            )
        return rows

    def product_rows(self) -> List[List[str]]:
        rows: List[List[str]] = []
        for name in sorted(self.products):
            product = self.products[name]
            base_materials = ", ".join(product.base_materials) if product.base_materials else "-"
            rows.append([product.name, base_materials])
        return rows


def _format_table(headers: List[str], rows: List[List[str]]) -> str:
    if not rows:
        widths = [len(h) for h in headers]
    else:
        widths = [len(h) for h in headers]
        for row in rows:
            for idx, value in enumerate(row):
                widths[idx] = max(widths[idx], len(value))

    def build_line(parts: List[str], sep: str = "|") -> str:
        return (
            sep
            + sep.join(
                f" {val}{' ' * (widths[idx] - len(val))} " for idx, val in enumerate(parts)
            )
            + sep
        )

    horizontal = "+" + "+".join("-" * (width + 2) for width in widths) + "+"
    output = [horizontal, build_line(headers), horizontal]
    for row in rows:
        output.append(build_line(row))
    output.append(horizontal)
    return "\n".join(output)


class InventoryCLI:
    def __init__(self, manager: Optional[InventoryManager] = None) -> None:
        self.manager = manager or InventoryManager()
        self.menu_items: List[Tuple[str, str, Optional[Callable[[], None]]]] = [
            ("1", "원료 데이터 입력/수정", self.handle_material_input),
            ("2", "제품 등록", self.handle_product_registration),
            ("3", "현황 출력", self.display_status),
            ("0", "종료", None),
        ]
        self.menu_actions = {key: handler for key, _, handler in self.menu_items}

    def run(self) -> None:
        while True:
            print("\n==== 생산계획 보조 CLI ====")
            for key, label, _ in self.menu_items:
                print(f"[{key}] {label}")
            choice = input("메뉴를 선택하세요: ").strip()
            if choice == "0":
                print("종료합니다.")
                return
            handler = self.menu_actions.get(choice)
            if handler is None:
                print("유효하지 않은 선택입니다. 다시 시도하세요.")
                continue
            if handler:
                try:
                    handler()
                except ValueError as exc:
                    print(f"입력 오류: {exc}")

    def handle_material_input(self) -> None:
        print("\n원료 데이터를 입력/수정합니다. 값을 비워두면 기존 수치를 유지합니다.")
        print(f"등록된 원료: {', '.join(sorted(self.manager.raw_materials))}")
        name = input("원료 이름을 입력하세요 (예: HV): ").strip().upper()
        if not name:
            print("원료 이름이 비어 있어 취소합니다.")
            return
        current = self.manager.raw_materials.get(name)
        if current is None:
            print(f"새 원료 '{name}'를 추가합니다.")
            current = RawMaterial(name=name)
        else:
            print(
                "현재 데이터 → 판매량:{}, 재고:{}, 생산가능:{}".format(
                    current.sales_volume,
                    current.inventory,
                    current.production_capacity,
                )
            )

        sales = self._prompt_float("판매량", default=current.sales_volume)
        inventory = self._prompt_float("재고량", default=current.inventory)
        capacity = self._prompt_float("생산 가능량", default=current.production_capacity)
        self.manager.upsert_raw_material(
            name,
            sales_volume=sales,
            inventory=inventory,
            production_capacity=capacity,
        )
        print(f"원료 '{name}' 정보가 저장되었습니다.")

    def handle_product_registration(self) -> None:
        print("\n새 제품을 등록합니다.")
        name = input("제품 이름: ").strip()
        if not name:
            print("제품 이름이 비어 있어 취소합니다.")
            return
        materials_input = input("사용하는 BASE 원료 목록을 입력하세요 (쉼표로 구분): ")
        base_materials = [item.strip() for item in materials_input.split(",") if item.strip()]
        product = self.manager.register_product(name, base_materials)
        print(
            "제품 '{}'이(가) 등록되었습니다. 사용 원료: {}".format(
                product.name, ", ".join(product.base_materials) or "-"
            )
        )

    def display_status(self) -> None:
        print("\n--- 원료 현황 ---")
        headers = ["원료", "판매량", "재고량", "생산 가능량"]
        rows = self.manager.material_rows()
        print(_format_table(headers, rows))

        print("\n--- 제품 등록 현황 ---")
        product_headers = ["제품", "사용 BASE 원료"]
        product_rows = self.manager.product_rows()
        if product_rows:
            print(_format_table(product_headers, product_rows))
        else:
            print("등록된 제품이 없습니다.")

    @staticmethod
    def _prompt_float(label: str, *, default: float) -> float:
        while True:
            raw = input(f"{label} (기본값 {default:.2f}): ").strip()
            if not raw:
                return default
            try:
                return float(raw)
            except ValueError:
                print("숫자를 입력하세요.")


class SmartScheduler:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("생산 계획 및 원료 현황 관리")
        self.root.geometry("1600x700")
        self.entries: Dict[str, tk.Entry] = {}
        self.emerg_var = tk.BooleanVar()
        self._build_gui()

    def _get_entry_value(self, key: str, fallback: float = 0.0) -> float:
        entry = self.entries.get(key)
        if entry is None:
            return fallback
        try:
            return float(entry.get())
        except (TypeError, ValueError):
            return fallback

    def _build_gui(self) -> None:
        config = [
            ("LV 포장 목표", "800", "b_goal"),
            ("C 펠렛 목표", "1080", "c_goal"),
            ("F 펠렛 목표", "960", "f_goal"),
            ("F 일일", "32.4", "f_daily"),
            ("G 펠렛 목표", "0", "g_goal"),
            ("G 일일", "20.0", "g_daily"),
            ("H 펠렛 목표", "1200", "h_goal"),
            ("H 일일", "40.0", "h_daily"),
            ("LLV 포장 목표", "800", "d_goal"),
            ("라인3 Capa", "180", "l3_cap"),
            ("라인2 Capa", "64.1", "l2_cap"),
            ("F펠렛라인Capa(S3)", "32.4", "f_line_capa"),
            ("C펠렛라인Capa(S3)", "36.0", "c_line_capa"),
            ("그라뉼라인Capa(S3)", "91.6", "granule_line_capa"),
            ("silo2 LV투입Capa", "89", "s2_daily"),
            ("silo2 긴급LV투입", "150", "s2_emerg"),
            ("S1+S2 포장Capa", "100", "s1s2_pack_capa"),
            ("S1 HV 최대Capa", "400", "s1_hv_max_capa"),
        ]

        form_frame = tk.Frame(self.root)
        form_frame.pack(fill=tk.X, padx=5, pady=5)

        columns_per_row = 4
        for index, (label_text, default_value, key) in enumerate(config):
            row, col = divmod(index, columns_per_row)
            label_column = col * 2
            entry_column = label_column + 1
            tk.Label(form_frame, text=label_text).grid(
                row=row, column=label_column, sticky="w", padx=2, pady=2
            )
            entry = tk.Entry(form_frame, width=8)
            entry.insert(0, default_value)
            entry.grid(row=row, column=entry_column, padx=5, pady=2)
            self.entries[key] = entry

        rows_of_config = math.ceil(len(config) / columns_per_row)
        tk.Checkbutton(
            form_frame,
            text="긴급 모드",
            variable=self.emerg_var,
        ).grid(row=rows_of_config, column=0, columnspan=2, sticky="w", padx=5, pady=2)

        tk.Button(form_frame, text="계획 생성", command=self._run).grid(
            row=0,
            column=columns_per_row * 2,
            rowspan=rows_of_config + 1,
            sticky="ns",
            padx=10,
            pady=5,
        )

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True)

        self.tree_s1_plan = self._create_treeview_tab(
            notebook,
            "S1 라인 생산 계획",
            ["일자", "제품명", "수량", "S1 HV 재고", "S1라인 포장량"],
        )
        self.tree_s2_plan = self._create_treeview_tab(
            notebook,
            "S2 라인 생산 계획",
            ["일자", "제품명1", "수량1", "제품명2", "수량2", "S2 LV 재고", "S2라인 포장량"],
        )
        s3_column_options = {
            "일자": {"width": 80},
            "S3 재고": {"width": 80},
            "S3 총포장": {"width": 80},
            "3Z-631(C) 제품": {"width": 120},
            "3Z-622(F) 제품": {"width": 120},
            "S3-Gran(LV) 제품": {"width": 120},
            "S3-Gran(LLV) 제품": {"width": 120},
            "3Z-631(C) 수량": {"width": 70},
            "3Z-622(F) 수량": {"width": 70},
            "S3-Gran(LV) 수량": {"width": 70},
            "S3-Gran(LLV) 수량": {"width": 70},
        }
        self.tree_s3_plan = self._create_treeview_tab(
            notebook,
            "S3 라인 생산 계획",
            [
                "일자",
                "3Z-631(C) 제품",
                "3Z-631(C) 수량",
                "3Z-622(F) 제품",
                "3Z-622(F) 수량",
                "S3-Gran(LV) 제품",
                "S3-Gran(LV) 수량",
                "S3-Gran(LLV) 제품",
                "S3-Gran(LLV) 수량",
                "S3 재고",
                "S3 총포장",
            ],
            column_options=s3_column_options,
        )
        self.tree_raw_prod = self._create_treeview_tab(
            notebook,
            "원료 생산",
            ["일자", "S3 LV생산", "LLV 생산", "NP3 생산", "HV 생산(S1향)", "S2 LV투입"],
        )
        s1_inventory_columns = ["일자", "S1 HV재고", "S1 LV재고", "S1 LLV재고"]
        s2_inventory_columns = ["일자", "S2 HV재고", "S2 LV재고", "S2 LLV재고"]
        s3_inventory_columns = ["일자", "S3 HV재고", "S3 LV재고", "S3 LLV재고", "S3 NP3재고"]
        self.tree_s1_inv = self._create_treeview_tab(
            notebook,
            "S1 Silo 재고",
            s1_inventory_columns,
            column_options={name: {"width": 120} for name in s1_inventory_columns},
        )
        self.tree_s2_inv = self._create_treeview_tab(
            notebook,
            "S2 Silo 재고",
            s2_inventory_columns,
            column_options={name: {"width": 120} for name in s2_inventory_columns},
        )
        self.tree_s3_inv = self._create_treeview_tab(
            notebook,
            "S3 Silo 재고",
            s3_inventory_columns,
            column_options={name: {"width": 120} for name in s3_inventory_columns},
        )

    def _create_treeview_tab(
        self,
        notebook: ttk.Notebook,
        title: str,
        columns: List[str],
        *,
        column_options: Optional[Dict[str, Dict[str, Any]]] = None,
        height: int = 20,
    ) -> ttk.Treeview:
        tab = tk.Frame(notebook)
        notebook.add(tab, text=title)
        container = tk.Frame(tab)
        container.pack(fill=tk.BOTH, expand=True)

        tree = ttk.Treeview(
            container,
            columns=columns,
            show="headings",
            height=height,
        )
        vertical_scroll = ttk.Scrollbar(container, orient=tk.VERTICAL, command=tree.yview)
        horizontal_scroll = ttk.Scrollbar(container, orient=tk.HORIZONTAL, command=tree.xview)
        tree.configure(yscrollcommand=vertical_scroll.set, xscrollcommand=horizontal_scroll.set)
        horizontal_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        vertical_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        column_options = column_options or {}
        for name in columns:
            options = column_options.get(name, {})
            width = int(options.get("width", 110))
            anchor = options.get("anchor", tk.CENTER)
            tree.heading(name, text=name)
            tree.column(name, width=width, anchor=anchor)

        return tree

    def _run(self) -> None:
        for tree in (
            self.tree_s1_plan,
            self.tree_s2_plan,
            self.tree_s3_plan,
            self.tree_raw_prod,
            self.tree_s1_inv,
            self.tree_s2_inv,
            self.tree_s3_inv,
        ):
            for row in tree.get_children():
                tree.delete(row)

        products_db: Dict[str, Dict[str, Any]] = {
            "C_PELLET": {
                "name": "C 펠렛",
                "target_key": "c_goal",
                "daily_limit_key": None,
                "recipe": [{"material_var_name": "LLV", "qty_per_unit": 1.0}],
            },
            "F_PELLET": {
                "name": "F 펠렛",
                "target_key": "f_goal",
                "daily_limit_key": "f_daily",
                "recipe": [{"material_var_name": "NP3", "qty_per_unit": 1.0}],
            },
            "H_PELLET": {
                "name": "H 펠렛",
                "target_key": "h_goal",
                "daily_limit_key": "h_daily",
                "recipe": [
                    {"material_var_name": "s1_HV", "qty_per_unit": 0.5},
                    {"material_var_name": "s2_LV", "qty_per_unit": 0.5},
                ],
            },
            "G_PELLET": {
                "name": "G 펠렛",
                "target_key": "g_goal",
                "daily_limit_key": "g_daily",
                "recipe": [{"material_var_name": "s1_HV", "qty_per_unit": 1.0}],
            },
            "LV_PACK": {
                "name": "LV 포장",
                "target_key": "b_goal",
                "daily_limit_key": None,
                "recipe": [{"material_var_name": "LV", "qty_per_unit": 1.0}],
            },
            "LLV_PACK": {
                "name": "LLV 포장",
                "target_key": "d_goal",
                "daily_limit_key": None,
                "recipe": [{"material_var_name": "LLV", "qty_per_unit": 1.0}],
            },
            "HV_PACK": {
                "name": "HV 포장",
                "target_key": None,
                "daily_limit_key": None,
                "recipe": [{"material_var_name": "s1_HV", "qty_per_unit": 1.0}],
            },
        }

        product_status: Dict[str, Dict[str, Any]] = {}
        for pid, info in products_db.items():
            entry = self.entries.get(info["target_key"]) if info["target_key"] else None
            raw_value = entry.get() if entry is not None else "0"
            try:
                target_goal = float(raw_value)
            except ValueError:
                messagebox.showwarning(
                    "입력 오류",
                    f"{info['name']} 목표 값이 잘못되었습니다. 0으로 처리합니다.",
                )
                target_goal = 0.0
            product_status[pid] = {
                "name": info["name"],
                "goal_orig": target_goal,
                "left": target_goal,
                "packed_today": 0.0,
                "packed_sum": 0.0,
            }

        start_date = datetime.now().date()
        stocks: Dict[str, Dict[str, float]] = {
            "S1": {"HV": LV_INIT, "LV": 0.0, "LLV": 0.0},
            "S2": {"HV": 0.0, "LV": LV_INIT, "LLV": 0.0},
            "S3": {"HV": 0.0, "LV": LV_INIT, "LLV": LLV_INIT, "NP3": NP3_INIT_VAL},
        }
        material_map: Dict[str, Tuple[str, str]] = {
            "s1_HV": ("S1", "HV"),
            "s2_LV": ("S2", "LV"),
            "LV": ("S3", "LV"),
            "LLV": ("S3", "LLV"),
            "NP3": ("S3", "NP3"),
        }

        switches = 0

        def schedule_product(pid: str, capacity_limit: float) -> float:
            if pid == "HV_PACK":
                return 0.0

            info = products_db[pid]
            status = product_status[pid]
            goal_left = status["left"]
            if goal_left <= 0:
                return 0.0

            allowed_by_capacity = goal_left
            if capacity_limit > 0:
                allowed_by_capacity = min(goal_left, capacity_limit)

            max_producible = allowed_by_capacity
            for ingredient in info["recipe"]:
                mapping = material_map.get(ingredient["material_var_name"])
                if mapping is None:
                    continue
                silo_name, material_name = mapping
                available_qty = stocks[silo_name][material_name]
                if pid == "C_PELLET" and silo_name == "S3" and material_name == "LLV":
                    available_qty = max(0.0, available_qty - LLV_SAFETY_STOCK_FOR_C)
                qty_per_unit = ingredient["qty_per_unit"]
                if qty_per_unit > 0:
                    max_producible = min(max_producible, available_qty / qty_per_unit)

            produced = max(0.0, min(allowed_by_capacity, max_producible))
            if produced <= 0:
                return 0.0

            status["packed_today"] = produced
            status["left"] = max(0.0, status["left"] - produced)
            status["packed_sum"] += produced

            for ingredient in info["recipe"]:
                mapping = material_map.get(ingredient["material_var_name"])
                if mapping is None:
                    continue
                silo_name, material_name = mapping
                qty_per_unit = ingredient["qty_per_unit"]
                stocks[silo_name][material_name] = max(
                    0.0, stocks[silo_name][material_name] - qty_per_unit * produced
                )

            return produced

        for day in range(DAYS):
            current_date = start_date + timedelta(days=day)
            date_str = current_date.strftime("%Y-%m-%d")

            for status in product_status.values():
                status["packed_today"] = 0.0

            remaining_s1s2_capacity = self._get_entry_value(
                "s1s2_pack_capa", PACK_S1_S2_COMBINED
            )
            s1_hv_max = self._get_entry_value("s1_hv_max_capa", S1_HV_MAX_CAPA)
            h_daily_limit = self._get_entry_value("h_daily", 0.0)
            g_daily_limit = self._get_entry_value("g_daily", 0.0)
            f_daily_limit = self._get_entry_value("f_daily", 0.0)
            granule_capacity = self._get_entry_value("granule_line_capa", PACK_S3)
            f_line_capacity = self._get_entry_value("f_line_capa", PACK_S3)
            c_line_capacity = self._get_entry_value("c_line_capa", PACK_S3)

            planned_remaining_s1s2 = remaining_s1s2_capacity
            planned_h_capacity = planned_remaining_s1s2
            if h_daily_limit > 0:
                planned_h_capacity = min(planned_h_capacity, h_daily_limit)
            planned_h = min(product_status["H_PELLET"]["left"], planned_h_capacity)
            planned_remaining_s1s2 = max(0.0, planned_remaining_s1s2 - planned_h)

            planned_g_capacity = planned_remaining_s1s2
            if g_daily_limit > 0:
                planned_g_capacity = min(planned_g_capacity, g_daily_limit)
            planned_g = min(product_status["G_PELLET"]["left"], planned_g_capacity)
            planned_remaining_s1s2 = max(0.0, planned_remaining_s1s2 - planned_g)

            planned_hv = max(0.0, min(planned_remaining_s1s2, s1_hv_max))

            planned_f_capacity = f_line_capacity
            if f_daily_limit > 0:
                planned_f_capacity = min(planned_f_capacity, f_daily_limit)
            planned_f = min(product_status["F_PELLET"]["left"], planned_f_capacity)

            planned_c = min(product_status["C_PELLET"]["left"], c_line_capacity)

            planned_granule_remaining = granule_capacity
            planned_lv = min(product_status["LV_PACK"]["left"], planned_granule_remaining)
            planned_granule_remaining = max(0.0, planned_granule_remaining - planned_lv)
            planned_llv = min(product_status["LLV_PACK"]["left"], planned_granule_remaining)

            required_s1_hv = 0.5 * planned_h + planned_g + planned_hv
            required_s2_lv = 0.5 * planned_h
            required_s3_lv = planned_lv
            required_s3_llv = planned_c + planned_llv
            required_np3 = planned_f

            raw_production_today = {
                "S3 LV생산": 0.0,
                "LLV 생산": 0.0,
                "NP3 생산": 0.0,
                "HV 생산(S1향)": 0.0,
                "S2 LV투입": 0.0,
            }

            s2_lv_capacity = self._get_entry_value("s2_daily", 0.0)
            if self.emerg_var.get():
                s2_lv_capacity += self._get_entry_value("s2_emerg", 0.0)
            target_s2_lv = max(required_s2_lv, S2_LV_MIN_STOCK_TRIGGER)
            if target_s2_lv > SILO2_CAP:
                target_s2_lv = SILO2_CAP
            current_s2_lv = stocks["S2"]["LV"]
            if current_s2_lv < target_s2_lv:
                produce_s2_lv = min(
                    target_s2_lv - current_s2_lv,
                    max(0.0, s2_lv_capacity),
                    SILO2_CAP - current_s2_lv,
                )
                if produce_s2_lv > 0:
                    stocks["S2"]["LV"] += produce_s2_lv
                    raw_production_today["S2 LV투입"] = produce_s2_lv

            s3_lv_capacity = max(0.0, self._get_entry_value("l3_cap", PACK_S3))
            target_s3_lv_base = min(
                INVENTORY_CAP,
                required_s3_lv + planned_lv * RESERVATION_BUFFER_DAYS,
            )
            current_s3_lv = stocks["S3"]["LV"]
            lv_needed_for_stock = max(0.0, target_s3_lv_base - current_s3_lv)
            lv_for_stock = min(
                lv_needed_for_stock,
                s3_lv_capacity,
                max(0.0, INVENTORY_CAP - current_s3_lv),
            )
            if lv_for_stock > 0:
                stocks["S3"]["LV"] += lv_for_stock
                raw_production_today["S3 LV생산"] += lv_for_stock

            remaining_lv_capacity = max(0.0, s3_lv_capacity - raw_production_today["S3 LV생산"])
            remaining_lv_inventory_room = max(0.0, INVENTORY_CAP - stocks["S3"]["LV"])

            s3_llv_capacity = self._get_entry_value("l2_cap", PACK_S3)
            llv_buffer = LLV_SAFETY_STOCK_FOR_C if product_status["C_PELLET"]["left"] > 0 else 0.0
            target_s3_llv = min(
                INVENTORY_CAP,
                required_s3_llv + planned_llv * RESERVATION_BUFFER_DAYS + llv_buffer,
            )
            current_s3_llv = stocks["S3"]["LLV"]
            if current_s3_llv < target_s3_llv:
                produce_s3_llv = min(
                    target_s3_llv - current_s3_llv,
                    max(0.0, s3_llv_capacity),
                    INVENTORY_CAP - current_s3_llv,
                )
                if produce_s3_llv > 0:
                    stocks["S3"]["LLV"] += produce_s3_llv
                    raw_production_today["LLV 생산"] = produce_s3_llv

            np3_capacity = max(0.0, NP3_TARGET_BATCH_PRODUCTION_SIZE)
            np3_target_level = required_np3 + planned_f * RESERVATION_BUFFER_DAYS
            if product_status["F_PELLET"]["left"] > 0:
                np3_target_level = max(np3_target_level, NP3_MIN_STOCK_BEFORE_CAMPAIGN)
                np3_target_level = max(np3_target_level, NP3_TARGET_BATCH_PRODUCTION_SIZE)
            np3_target_level = min(NP3_MAX_INV, np3_target_level)
            current_np3 = stocks["S3"]["NP3"]
            np3_deficit = max(0.0, np3_target_level - current_np3)
            np3_capacity = min(np3_capacity, max(0.0, NP3_MAX_INV - current_np3))
            potential_np3 = min(np3_deficit, np3_capacity)
            np3_produced = 0.0
            if (
                potential_np3 > 0
                and NP3_PRODUCTION_RATE_IN_CAMPAIGN > 0
                and remaining_lv_capacity > 0
                and remaining_lv_inventory_room > 0
            ):
                lv_capacity_for_np3 = min(remaining_lv_capacity, remaining_lv_inventory_room)
                max_np3_based_on_lv = lv_capacity_for_np3 * NP3_PRODUCTION_RATE_IN_CAMPAIGN
                np3_produced = min(potential_np3, max_np3_based_on_lv)
                if np3_produced > 0:
                    lv_for_np3 = np3_produced / NP3_PRODUCTION_RATE_IN_CAMPAIGN
                    stocks["S3"]["LV"] += lv_for_np3
                    raw_production_today["S3 LV생산"] += lv_for_np3
                    remaining_lv_capacity = max(0.0, remaining_lv_capacity - lv_for_np3)
                    remaining_lv_inventory_room = max(
                        0.0, INVENTORY_CAP - stocks["S3"]["LV"]
                    )
                    stocks["S3"]["NP3"] += np3_produced
                    raw_production_today["NP3 생산"] = np3_produced

            hv_capacity = s1_hv_max
            target_s1_hv = min(
                INVENTORY_CAP,
                required_s1_hv + planned_hv * RESERVATION_BUFFER_DAYS,
            )
            current_s1_hv = stocks["S1"]["HV"]
            if current_s1_hv < target_s1_hv:
                produce_hv = min(
                    target_s1_hv - current_s1_hv,
                    max(0.0, hv_capacity),
                    INVENTORY_CAP - current_s1_hv,
                )
                if produce_hv > 0:
                    stocks["S1"]["HV"] += produce_hv
                    raw_production_today["HV 생산(S1향)"] = produce_hv

            # S2 생산 (H, G 펠렛)
            h_capacity = remaining_s1s2_capacity
            if h_daily_limit > 0:
                h_capacity = min(h_capacity, h_daily_limit)
            packed_h = schedule_product("H_PELLET", h_capacity)
            if packed_h > 0:
                remaining_s1s2_capacity = max(0.0, remaining_s1s2_capacity - packed_h)
                switches += 1

            g_capacity = remaining_s1s2_capacity
            if g_daily_limit > 0:
                g_capacity = min(g_capacity, g_daily_limit)
            packed_g = schedule_product("G_PELLET", g_capacity)
            if packed_g > 0:
                remaining_s1s2_capacity = max(0.0, remaining_s1s2_capacity - packed_g)
                switches += 1

            # S1 HV 포장 (남은 capa로)
            hv_available = stocks["S1"]["HV"]
            hv_capacity = remaining_s1s2_capacity
            if s1_hv_max > 0:
                hv_capacity = min(hv_capacity, s1_hv_max)
            hv_amount = max(0.0, min(hv_available, hv_capacity))
            product_status["HV_PACK"]["packed_today"] = hv_amount
            if hv_amount > 0:
                product_status["HV_PACK"]["packed_sum"] += hv_amount
                stocks["S1"]["HV"] = max(0.0, stocks["S1"]["HV"] - hv_amount)
                remaining_s1s2_capacity = max(
                    0.0, remaining_s1s2_capacity - hv_amount
                )
                switches += 1

            # S3 생산 (C, F, LV, LLV)
            f_capacity = f_line_capacity
            if f_daily_limit > 0:
                f_capacity = min(f_capacity, f_daily_limit)
            packed_f = schedule_product("F_PELLET", f_capacity)
            if packed_f > 0:
                switches += 1

            packed_c = schedule_product("C_PELLET", c_line_capacity)
            if packed_c > 0:
                switches += 1

            remaining_granule_capacity = granule_capacity
            lv_capacity = min(remaining_granule_capacity, product_status["LV_PACK"]["left"])
            packed_lv = schedule_product("LV_PACK", lv_capacity)
            if packed_lv > 0:
                remaining_granule_capacity = max(0.0, remaining_granule_capacity - packed_lv)
                switches += 1

            llv_capacity = min(remaining_granule_capacity, product_status["LLV_PACK"]["left"])
            packed_llv = schedule_product("LLV_PACK", llv_capacity)
            if packed_llv > 0:
                remaining_granule_capacity = max(
                    0.0, remaining_granule_capacity - packed_llv
                )
                switches += 1

            s1_pack_val = product_status["HV_PACK"]["packed_today"]
            s2_pack_val = packed_h + packed_g
            s3_pack_val = (
                packed_c + packed_f + packed_lv + packed_llv
            )

            s2_inv_val = stocks["S2"]["LV"]
            s3_inv_val = (
                stocks["S3"]["LV"]
                + stocks["S3"]["LLV"]
                + stocks["S3"].get("NP3", 0.0)
            )

            s2_lv_input = raw_production_today["S2 LV투입"]

            self.tree_s1_plan.insert(
                "",
                "end",
                values=(
                    date_str,
                    product_status["HV_PACK"]["name"],
                    round(product_status["HV_PACK"]["packed_today"], 1),
                    round(stocks["S1"]["HV"], 1),
                    round(s1_pack_val, 1),
                ),
            )
            self.tree_s2_plan.insert(
                "",
                "end",
                values=(
                    date_str,
                    product_status["H_PELLET"]["name"],
                    round(product_status["H_PELLET"]["packed_today"], 1),
                    product_status["G_PELLET"]["name"],
                    round(product_status["G_PELLET"]["packed_today"], 1),
                    round(s2_inv_val, 1),
                    round(s2_pack_val, 1),
                ),
            )
            self.tree_s3_plan.insert(
                "",
                "end",
                values=(
                    date_str,
                    product_status["C_PELLET"]["name"],
                    round(product_status["C_PELLET"]["packed_today"], 1),
                    product_status["F_PELLET"]["name"],
                    round(product_status["F_PELLET"]["packed_today"], 1),
                    product_status["LV_PACK"]["name"],
                    round(product_status["LV_PACK"]["packed_today"], 1),
                    product_status["LLV_PACK"]["name"],
                    round(product_status["LLV_PACK"]["packed_today"], 1),
                    round(s3_inv_val, 1),
                    round(s3_pack_val, 1),
                ),
            )

            self.tree_raw_prod.insert(
                "",
                "end",
                values=(
                    date_str,
                    round(raw_production_today["S3 LV생산"], 1),
                    round(raw_production_today["LLV 생산"], 1),
                    round(raw_production_today["NP3 생산"], 1),
                    round(raw_production_today["HV 생산(S1향)"], 1),
                    round(s2_lv_input, 1),
                ),
            )

            self.tree_s1_inv.insert(
                "",
                "end",
                values=(
                    date_str,
                    round(stocks["S1"].get("HV", 0.0), 1),
                    round(stocks["S1"].get("LV", 0.0), 1),
                    round(stocks["S1"].get("LLV", 0.0), 1),
                ),
            )
            self.tree_s2_inv.insert(
                "",
                "end",
                values=(
                    date_str,
                    round(stocks["S2"].get("HV", 0.0), 1),
                    round(stocks["S2"].get("LV", 0.0), 1),
                    round(stocks["S2"].get("LLV", 0.0), 1),
                ),
            )
            self.tree_s3_inv.insert(
                "",
                "end",
                values=(
                    date_str,
                    round(stocks["S3"].get("HV", 0.0), 1),
                    round(stocks["S3"].get("LV", 0.0), 1),
                    round(stocks["S3"].get("LLV", 0.0), 1),
                    round(stocks["S3"].get("NP3", 0.0), 1),
                ),
            )

            remaining_targets = any(
                status["left"] > 0.001
                for pid, status in product_status.items()
                if products_db.get(pid, {}).get("target_key")
            )
            if not remaining_targets:
                break

        summary_text = "생산 요약 및 목표 달성 현황\n" + "─" * 30 + "\n"
        products_summary_data_list = []
        for p_stat in product_status.values():
            products_summary_data_list.append(
                (
                    p_stat["name"],
                    p_stat["goal_orig"],
                    p_stat["left"],
                    p_stat["packed_sum"],
                )
            )

        total_goals_sum = 0.0
        relevant_produced_sum = 0.0
        all_achieved = True
        for name, goal, left, total_packed in products_summary_data_list:
            current_left = max(0.0, left)
            if goal > 0:
                total_goals_sum += goal
            if goal > 0 and current_left > 0.001:
                all_achieved = False
            achieved_status = (
                "달성"
                if current_left <= 0.001 and goal > 0
                else ("해당 없음" if goal <= 0 else "미달성")
            )
            summary_text += (
                f"{name}:\n  목표: {goal:.1f}, 생산: {total_packed:.1f}, 잔여: {current_left:.1f}\n"
                f"  달성 여부: {achieved_status}"
            )
            if current_left > 0.001 and goal > 0:
                summary_text += f" (부족분: {current_left:.1f})\n\n"
            else:
                summary_text += "\n\n"

            if goal > 0:
                relevant_produced_sum += total_packed

        overall_achievement_rate = (
            (relevant_produced_sum / total_goals_sum * 100)
            if total_goals_sum > 0
            else (100 if relevant_produced_sum > 0 else 0)
        )
        summary_text += f"총 모드 전환 횟수: {switches}회\n"
        summary_text += f"전체 목표 달성률 (목표량 기준): {overall_achievement_rate:.2f}%\n"
        summary_text += (
            "모든 '목표' 제품 달성 여부: "
            + (
                "완료"
                if all_achieved and total_goals_sum > 0
                else ("해당 없음" if total_goals_sum == 0 else "부분 달성")
            )
            + "\n"
        )

        summary_window = tk.Toplevel(self.root)
        summary_window.title("생산 요약 보고")
        summary_window.geometry("450x550")
        text_frame = tk.Frame(summary_window)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        st_widget = tk.Text(text_frame, wrap=tk.WORD, height=23, width=60)
        scroll = tk.Scrollbar(text_frame, command=st_widget.yview)
        st_widget.configure(yscrollcommand=scroll.set)
        st_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        st_widget.insert(tk.END, summary_text)
        st_widget.config(state=tk.DISABLED)
        tk.Button(summary_window, text="닫기", command=summary_window.destroy).pack(pady=10)
        summary_window.grab_set()
        summary_window.focus_set()
        summary_window.wait_window()


def _run_gui() -> None:
    root = tk.Tk()
    SmartScheduler(root)
    root.mainloop()


def _run_cli() -> None:
    cli = InventoryCLI()
    cli.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="SmartScheduler GUI 또는 CLI를 실행합니다."
    )
    parser.add_argument(
        "--mode",
        choices=["gui", "cli"],
        default="gui",
        help="실행 모드를 선택합니다 (gui 또는 cli). 기본값은 gui입니다.",
    )
    args = parser.parse_args()

    if args.mode == "cli":
        _run_cli()
    else:
        _run_gui()
