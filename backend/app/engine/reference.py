"""Reference data taken from seed/ — generated once, then checked by tests.

Source files: seed/bom_reference_600m2.csv and seed/work_packages.json.
No I/O here: the engine imports these constants.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkPackageMeta:
    id: str
    name: str
    months: str
    budget_sar: int  # seed baseline, used for calibration only


@dataclass(frozen=True)
class RefLine:
    id: str
    category: str
    item: str
    unit: str
    qty_per_m2_bua: float
    rate_sar: float
    wp_split: tuple[tuple[str, float], ...]  # (work package id, share of amount)


WORK_PACKAGES: tuple[WorkPackageMeta, ...] = (
    WorkPackageMeta('WP1_site_foundations', 'Site preparation & foundations', '1-2', 300000),
    WorkPackageMeta('WP2_structure', 'Structural works', '3-5', 480000),
    WorkPackageMeta('WP3_mep', 'MEP systems', '6-8', 560000),
    WorkPackageMeta('WP4_finishes', 'Architectural finishes', '8-12', 620000),
    WorkPackageMeta('WP5_external', 'External works & handover', '12-14', 140000),
)


REFERENCE_BOM: tuple[RefLine, ...] = (
    RefLine('M01', 'civil_structural', 'Ready-mix concrete (various grades)', 'm³', 0.51667, 320.0, (('WP1_site_foundations', 0.35), ('WP2_structure', 0.65))),
    RefLine('M02', 'civil_structural', 'Reinforcement steel bars', 't', 0.08, 3300.0, (('WP1_site_foundations', 0.35), ('WP2_structure', 0.65))),
    RefLine('M03', 'civil_structural', 'Concrete masonry blocks', 'pc', 24.16667, 6.0, (('WP2_structure', 1.0),)),
    RefLine('M04', 'civil_structural', 'Cement for mortar / plaster', 'bag', 2.25, 17.0, (('WP2_structure', 1.0),)),
    RefLine('M05', 'civil_structural', 'Washed sand', 'm³', 0.3, 75.0, (('WP2_structure', 1.0),)),
    RefLine('M06', 'civil_structural', 'Crushed aggregate / backfill', 'm³', 0.35, 65.0, (('WP1_site_foundations', 1.0),)),
    RefLine('M07', 'civil_structural', 'Below-grade waterproofing membrane', 'm²', 0.91667, 30.0, (('WP1_site_foundations', 1.0),)),
    RefLine('M08', 'civil_structural', 'Roof thermal / waterproof insulation', 'm²', 0.5, 65.0, (('WP2_structure', 1.0),)),
    RefLine('M09', 'civil_structural', 'Anti-termite soil treatment', 'm²', 0.53333, 12.0, (('WP1_site_foundations', 1.0),)),
    RefLine('M10', 'architectural', 'Internal plaster materials', 'm²', 2.66667, 24.0, (('WP4_finishes', 1.0),)),
    RefLine('M11', 'architectural', 'Interior floor porcelain / tile', 'm²', 0.86667, 90.0, (('WP4_finishes', 1.0),)),
    RefLine('M12', 'architectural', 'Wall tiles (wet areas)', 'm²', 0.5, 80.0, (('WP4_finishes', 1.0),)),
    RefLine('M13', 'architectural', 'Interior paint system', 'm²', 3.66667, 15.0, (('WP4_finishes', 1.0),)),
    RefLine('M14', 'architectural', 'Exterior coating / cladding', 'm²', 1.0, 65.0, (('WP4_finishes', 1.0),)),
    RefLine('M15', 'architectural', 'Interior doors and hardware', 'set', 0.04, 1250.0, (('WP4_finishes', 1.0),)),
    RefLine('M16', 'architectural', 'Exterior / entrance doors', 'set', 0.00667, 3800.0, (('WP4_finishes', 1.0),)),
    RefLine('M17', 'architectural', 'Aluminum windows and glazing', 'm²', 0.2, 650.0, (('WP4_finishes', 1.0),)),
    RefLine('M18', 'architectural', 'Kitchen cabinetry / counters', 'lot', 0.00167, 45000.0, (('WP4_finishes', 1.0),)),
    RefLine('M19', 'architectural', 'Sanitary fixtures / accessories', 'set', 0.02, 1700.0, (('WP4_finishes', 1.0),)),
    RefLine('M20', 'architectural', 'Gypsum board false ceilings', 'm²', 0.75, 55.0, (('WP4_finishes', 1.0),)),
    RefLine('M21', 'plumbing_drainage', 'PPR water piping, mixed sizes', 'm', 1.41667, 22.0, (('WP3_mep', 1.0),)),
    RefLine('M22', 'plumbing_drainage', 'Drainage / vent piping, mixed sizes', 'm', 1.08333, 28.0, (('WP3_mep', 1.0),)),
    RefLine('M23', 'plumbing_drainage', 'Water pumps and controls', 'set', 0.00333, 4500.0, (('WP3_mep', 1.0),)),
    RefLine('M24', 'plumbing_drainage', 'Water tanks', 'set', 0.00333, 5500.0, (('WP3_mep', 1.0),)),
    RefLine('M25', 'plumbing_drainage', 'Septic tank / sewer connection', 'lot', 0.00167, 18000.0, (('WP3_mep', 1.0),)),
    RefLine('M26', 'hvac', 'Split / ducted AC equipment', 'TR', 0.04667, 4500.0, (('WP3_mep', 1.0),)),
    RefLine('M27', 'hvac', 'Refrigerant piping and insulation', 'm', 0.83333, 60.0, (('WP3_mep', 1.0),)),
    RefLine('M28', 'electrical', 'Power / lighting cables', 'm', 7.5, 11.0, (('WP3_mep', 1.0),)),
    RefLine('M29', 'electrical', 'Conduits, fittings and boxes', 'm', 5.83333, 5.0, (('WP3_mep', 1.0),)),
    RefLine('M30', 'electrical', 'Distribution boards / breakers', 'set', 0.00833, 7500.0, (('WP3_mep', 1.0),)),
    RefLine('M31', 'electrical', 'Switches, sockets and accessories', 'point', 0.33333, 85.0, (('WP3_mep', 1.0),)),
    RefLine('M32', 'electrical', 'Lighting fixtures', 'pc', 0.21667, 230.0, (('WP3_mep', 1.0),)),
    RefLine('M33', 'electrical', 'Data / low-current cabling', 'm', 1.5, 7.0, (('WP3_mep', 1.0),)),
    RefLine('M34', 'external_works', 'Paving / hardscape', 'm²', 0.36667, 105.0, (('WP5_external', 1.0),)),
    RefLine('M35', 'external_works', 'Boundary gate / metalwork', 'lot', 0.00167, 24000.0, (('WP5_external', 1.0),)),
    RefLine('M36', 'external_works', 'Landscape irrigation / planting', 'lot', 0.00167, 18000.0, (('WP5_external', 1.0),)),
)
