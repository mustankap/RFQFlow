"""Draft D2 input models; replace with team contracts when agreed."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InputModel(BaseModel):
    # Keep upstream fields we do not consume, including source excerpts.
    model_config = ConfigDict(extra="allow", allow_inf_nan=False)


class Thickness(InputModel):
    raw: str | None = None
    normalized_inches: float | None = Field(default=None, gt=0)
    conversion_status: str


class Dimension(InputModel):
    raw: str | None = None
    value_in: float | None = Field(default=None, gt=0)
    unit_status: str


class Specification(InputModel):
    material_family: str | None
    material_grade: str | None
    product_form: str | None
    quantity: float | None = Field(gt=0)
    quantity_unit: str | None
    thickness: Thickness
    width: Dimension
    length: Dimension


class RFQLine(InputModel):
    line_id: str = Field(min_length=1)
    original_text: str = Field(min_length=1)
    source_reference: dict
    specification: Specification
    missing_fields: list[str]
    ambiguities: list[str]
    extraction_status: str


class ParsedRFQ(InputModel):
    rfq_id: str = Field(min_length=1)
    original_text: str
    items: list[RFQLine] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_lines(self):
        if len({line.line_id for line in self.items}) != len(self.items):
            raise ValueError("RFQ line IDs must be unique")
        return self


class Product(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    sku: str = Field(min_length=1)
    supplier_name: str
    description: str
    material_family: str
    material_grade: str
    product_form: str
    thickness_in: float = Field(gt=0)
    width_in: float = Field(gt=0)
    length_in: float = Field(gt=0)
    source_id: str = Field(min_length=1)
    source_type: str
    source_date: str
    is_synthetic: bool


class SyntheticCatalog(BaseModel):
    catalog_version: str
    is_synthetic: Literal[True]
    products: list[Product] = Field(min_length=1)

    @model_validator(mode="after")
    def check_records(self):
        if len({p.sku for p in self.products}) != len(self.products):
            raise ValueError("Catalog SKUs must be unique")
        if not all(p.is_synthetic for p in self.products):
            raise ValueError("Demo catalog must contain only synthetic products")
        return self
