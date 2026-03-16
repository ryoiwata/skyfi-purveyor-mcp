"""Pydantic models for all SkyFi Platform API request and response types."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enums — values must match SkyFi's API exactly (including spaces)
# ---------------------------------------------------------------------------


class ApiProvider(StrEnum):
    """Satellite image providers available on SkyFi."""

    SIWEI = "SIWEI"
    SATELLOGIC = "SATELLOGIC"
    UMBRA = "UMBRA"
    GEOSAT = "GEOSAT"
    SENTINEL1_CREODIAS = "SENTINEL1_CREODIAS"
    SENTINEL2 = "SENTINEL2"
    SENTINEL2_CREODIAS = "SENTINEL2_CREODIAS"
    PLANET = "PLANET"
    IMPRO = "IMPRO"
    URBAN_SKY = "URBAN_SKY"
    NSL = "NSL"
    VEXCEL = "VEXCEL"
    ICEYE_US = "ICEYE_US"
    VANTOR = "VANTOR"


class ProductType(StrEnum):
    """Satellite imagery product types."""

    DAY = "DAY"
    NIGHT = "NIGHT"
    VIDEO = "VIDEO"
    MULTISPECTRAL = "MULTISPECTRAL"
    HYPERSPECTRAL = "HYPERSPECTRAL"
    SAR = "SAR"
    STEREO = "STEREO"
    BASEMAP = "BASEMAP"


class Resolution(StrEnum):
    """Image resolution tiers — NOTE: values contain spaces as per SkyFi API."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY HIGH"
    SUPER_HIGH = "SUPER HIGH"
    ULTRA_HIGH = "ULTRA HIGH"
    CM_30 = "CM 30"
    CM_50 = "CM 50"
    SPOT = "SPOT"
    SPOT_FINE = "SPOT FINE"
    SLEA = "SLEA"
    DWELL = "DWELL"
    DWELL_FINE = "DWELL FINE"
    STRIP = "STRIP"
    SCAN = "SCAN"


class DeliveryDriver(StrEnum):
    """Delivery destination driver types."""

    GS = "GS"
    S3 = "S3"
    AZURE = "AZURE"
    DELIVERY_CONFIG = "DELIVERY_CONFIG"
    S3_SERVICE_ACCOUNT = "S3_SERVICE_ACCOUNT"
    GS_SERVICE_ACCOUNT = "GS_SERVICE_ACCOUNT"
    AZURE_SERVICE_ACCOUNT = "AZURE_SERVICE_ACCOUNT"
    NONE = "NONE"


class DeliveryStatus(StrEnum):
    """Order delivery lifecycle statuses."""

    CREATED = "CREATED"
    STARTED = "STARTED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    PLATFORM_FAILED = "PLATFORM_FAILED"
    PROVIDER_PENDING = "PROVIDER_PENDING"
    PROVIDER_COMPLETE = "PROVIDER_COMPLETE"
    PROVIDER_FAILED = "PROVIDER_FAILED"
    PROCESSING_PENDING = "PROCESSING_PENDING"
    PROCESSING_COMPLETE = "PROCESSING_COMPLETE"
    PROCESSING_FAILED = "PROCESSING_FAILED"
    DELIVERY_PENDING = "DELIVERY_PENDING"
    DELIVERY_COMPLETED = "DELIVERY_COMPLETED"
    DELIVERY_FAILED = "DELIVERY_FAILED"
    INTERNAL_IMAGE_PROCESSING_PENDING = "INTERNAL_IMAGE_PROCESSING_PENDING"


class OrderType(StrEnum):
    """Order type: archive or tasking."""

    ARCHIVE = "ARCHIVE"
    TASKING = "TASKING"


class SortColumn(StrEnum):
    """Columns available for sorting order lists."""

    CREATED_AT = "created_at"
    LAST_MODIFIED = "last_modified"
    CUSTOMER_ITEM_COST = "customer_item_cost"
    STATUS = "status"


class SortDirection(StrEnum):
    """Sort direction."""

    ASC = "asc"
    DESC = "desc"


class DeliverableType(StrEnum):
    """Downloadable deliverable types."""

    IMAGE = "image"
    PAYLOAD = "payload"
    COG = "cog"
    BABA = "baba"


class SarProductType(StrEnum):
    """SAR-specific product types."""

    GEC = "GEC"
    SICD = "SICD"
    SIDD = "SIDD"
    CPHD = "CPHD"


class SarPolarisation(StrEnum):
    """SAR polarisation modes."""

    HH = "HH"
    VV = "VV"


class FeasibilityCheckStatus(StrEnum):
    """Feasibility task status."""

    PENDING = "PENDING"
    STARTED = "STARTED"
    COMPLETE = "COMPLETE"
    ERROR = "ERROR"


# ---------------------------------------------------------------------------
# Typed delivery params (DESIGN_DECISIONS §9)
# ---------------------------------------------------------------------------


class S3DeliveryParams(BaseModel):
    """AWS S3 delivery parameters."""

    bucket: str = Field(description="S3 bucket name")
    region: str = Field(description="AWS region (e.g. us-east-1)")
    access_key_id: str | None = Field(default=None, description="AWS access key ID")
    secret_access_key: str | None = Field(default=None, description="AWS secret access key")
    prefix: str | None = Field(default=None, description="Optional key prefix")


class GCSDeliveryParams(BaseModel):
    """Google Cloud Storage delivery parameters."""

    bucket: str = Field(description="GCS bucket name")
    credentials: dict[str, Any] | None = Field(
        default=None, description="Service account credentials JSON"
    )
    prefix: str | None = Field(default=None, description="Optional object prefix")


class AzureDeliveryParams(BaseModel):
    """Azure Blob Storage delivery parameters."""

    container: str = Field(description="Azure container name")
    connection_string: str | None = Field(default=None, description="Azure connection string")
    sas_token: str | None = Field(default=None, description="Azure SAS token")
    account_name: str | None = Field(default=None, description="Azure storage account name")
    prefix: str | None = Field(default=None, description="Optional blob prefix")


# ---------------------------------------------------------------------------
# Core / auth
# ---------------------------------------------------------------------------


class WhoamiUser(BaseModel):
    """Authenticated user information."""

    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    organization_id: uuid.UUID | None = Field(default=None, alias="organizationId")
    email: str
    first_name: str = Field(alias="firstName")
    last_name: str = Field(alias="lastName")
    is_demo_account: bool = Field(default=True, alias="isDemoAccount")
    current_budget_usage: int = Field(alias="currentBudgetUsage", description="Cents")
    budget_amount: int = Field(alias="budgetAmount", description="Cents")
    has_valid_shared_card: bool = Field(alias="hasValidSharedCard")

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


# ---------------------------------------------------------------------------
# Health / ping
# ---------------------------------------------------------------------------


class PongResponse(BaseModel):
    """Response from /ping."""

    model_config = ConfigDict(extra="ignore")

    message: str | None = None


class StatusResponse(BaseModel):
    """Generic status response."""

    model_config = ConfigDict(extra="ignore")

    status: str | None = None


# ---------------------------------------------------------------------------
# Archive models
# ---------------------------------------------------------------------------


class Archive(BaseModel):
    """A single satellite archive image."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    archive_id: str = Field(alias="archiveId")
    provider: ApiProvider
    constellation: str
    product_type: ProductType = Field(alias="productType")
    platform_resolution: float = Field(alias="platformResolution")
    resolution: str  # Resolution enum values include spaces — keep as str
    capture_timestamp: datetime = Field(alias="captureTimestamp")
    cloud_coverage_percent: float | None = Field(default=None, alias="cloudCoveragePercent")
    off_nadir_angle: float | None = Field(default=None, alias="offNadirAngle")
    footprint: str  # WKT POLYGON
    min_sq_km: float = Field(alias="minSqKm")
    max_sq_km: float = Field(alias="maxSqKm")
    price_for_one_square_km: float = Field(alias="priceForOneSquareKm", description="USD")
    price_for_one_square_km_cents: int = Field(alias="priceForOneSquareKmCents")
    price_full_scene: float = Field(alias="priceFullScene", description="USD")
    open_data: bool = Field(default=False, alias="openData")
    total_area_square_km: float = Field(alias="totalAreaSquareKm")
    delivery_time_hours: float = Field(default=12.0, alias="deliveryTimeHours")
    thumbnail_urls: dict[str, str] | None = Field(default=None, alias="thumbnailUrls")
    gsd: float
    tiles_url: str | None = Field(default=None, alias="tilesUrl")


class ArchiveResponse(Archive):
    """Archive search result with AOI overlap information."""

    overlap_ratio: float = Field(alias="overlapRatio", description="Ratio 0-1")
    overlap_sqkm: float = Field(alias="overlapSqkm")


class GetArchivesRequest(BaseModel):
    """Request body for POST /archives."""

    aoi: str = Field(description="WKT POLYGON")
    from_date: datetime | None = Field(default=None, alias="fromDate")
    to_date: datetime | None = Field(default=None, alias="toDate")
    max_cloud_coverage_percent: float | None = Field(
        default=None, alias="maxCloudCoveragePercent"
    )
    max_off_nadir_angle: float | None = Field(default=None, alias="maxOffNadirAngle")
    resolutions: list[str] | None = Field(default=None)
    product_types: list[ProductType] | None = Field(default=None, alias="productTypes")
    providers: list[ApiProvider] | None = Field(default=None)
    open_data: bool | None = Field(default=None, alias="openData")
    min_overlap_ratio: float | None = Field(default=None, alias="minOverlapRatio")
    page_number: int | None = Field(default=None, alias="pageNumber")
    page_size: int = Field(default=100, alias="pageSize", ge=1, le=100)

    model_config = ConfigDict(populate_by_name=True)

    def model_dump_skyfi(self) -> dict[str, Any]:
        """Serialize for SkyFi API (camelCase, exclude None, JSON-safe types)."""
        return self.model_dump(by_alias=True, exclude_none=True, mode="json")


class GetArchivesResponse(BaseModel):
    """Response from POST /archives."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    archives: list[ArchiveResponse]
    next_page: str | None = Field(default=None, alias="nextPage")
    total: int | None = Field(default=None)


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


class PricingRequest(BaseModel):
    """Request body for POST /pricing."""

    aoi: str | None = Field(default=None, description="WKT POLYGON (optional)")

    model_config = ConfigDict(populate_by_name=True)


# ---------------------------------------------------------------------------
# Feasibility
# ---------------------------------------------------------------------------


class CloudCoverage(BaseModel):
    """Cloud coverage data point."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    date: datetime
    cloud_coverage: float = Field(alias="cloudCoverage")


class WeatherDetails(BaseModel):
    """Detailed weather information."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    weather_score: float = Field(alias="weatherScore")
    clouds: list[CloudCoverage] | None = Field(default=None)


class WeatherScore(BaseModel):
    """Weather feasibility score."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    weather_score: float = Field(alias="weatherScore")
    weather_details: WeatherDetails | None = Field(default=None, alias="weatherDetails")


class Opportunity(BaseModel):
    """A specific satellite pass opportunity."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    window_start: datetime = Field(alias="windowStart")
    window_end: datetime = Field(alias="windowEnd")
    satellite_id: str | None = Field(default=None, alias="satelliteId")
    provider_window_id: uuid.UUID | None = Field(default=None, alias="providerWindowId")
    provider_metadata: dict[str, Any] = Field(default_factory=dict, alias="providerMetadata")


class ProviderScore(BaseModel):
    """Per-provider feasibility score."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    provider: str | None = None
    score: float
    status: FeasibilityCheckStatus | None = None
    reference: str | None = None
    opportunities: list[Opportunity] = Field(default_factory=list)


class ProviderCombinedScore(BaseModel):
    """Combined provider score."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    score: float
    provider_scores: list[ProviderScore] | None = Field(default=None, alias="providerScores")


class FeasibilityScore(BaseModel):
    """Overall feasibility score with breakdown."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    feasibility: float
    weather_score: WeatherScore | None = Field(default=None, alias="weatherScore")
    provider_score: ProviderCombinedScore | None = Field(default=None, alias="providerScore")


class FeasibilityRequest(BaseModel):
    """Request body for POST /feasibility."""

    aoi: str = Field(description="WKT POLYGON")
    product_type: ProductType = Field(alias="productType")
    resolution: str
    start_date: datetime = Field(alias="startDate")
    end_date: datetime = Field(alias="endDate")
    max_cloud_coverage_percent: float | None = Field(
        default=None, alias="maxCloudCoveragePercent"
    )
    priority_item: bool | None = Field(default=None, alias="priorityItem")
    required_provider: str | None = Field(default=None, alias="requiredProvider")
    sar_parameters: dict[str, Any] = Field(default_factory=dict, alias="sarParameters")

    model_config = ConfigDict(populate_by_name=True)

    def model_dump_skyfi(self) -> dict[str, Any]:
        """Serialize for SkyFi API."""
        return self.model_dump(by_alias=True, exclude_none=True, mode="json")


class FeasibilityResponse(BaseModel):
    """Response from POST /feasibility or GET /feasibility/{id}."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: uuid.UUID
    valid_until: datetime = Field(alias="validUntil")
    overall_score: FeasibilityScore | None = Field(default=None, alias="overallScore")


# ---------------------------------------------------------------------------
# Pass predictions
# ---------------------------------------------------------------------------


class PassPredictionRequest(BaseModel):
    """Request body for POST /feasibility/pass-prediction."""

    aoi: str = Field(description="WKT POLYGON")
    from_date: datetime = Field(alias="fromDate")
    to_date: datetime = Field(alias="toDate")
    product_types: list[ProductType] | None = Field(default=None, alias="productTypes")
    resolutions: list[str] | None = None
    max_off_nadir_angle: float | None = Field(default=30.0, alias="maxOffNadirAngle")

    model_config = ConfigDict(populate_by_name=True)

    def model_dump_skyfi(self) -> dict[str, Any]:
        """Serialize for SkyFi API."""
        return self.model_dump(by_alias=True, exclude_none=True, mode="json")


class Pass(BaseModel):
    """A satellite pass prediction."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    provider: ApiProvider
    satname: str
    satid: str
    noradid: str
    node: str
    product_type: ProductType = Field(alias="productType")
    resolution: str
    lat: float
    lon: float
    pass_date: datetime = Field(alias="passDate")
    mean_t: int = Field(alias="meanT")
    off_nadir_angle: float = Field(alias="offNadirAngle")
    solar_elevation_angle: float = Field(alias="solarElevationAngle")
    min_square_kms: float = Field(alias="minSquareKms")
    max_square_kms: float = Field(alias="maxSquareKms")
    price_for_one_square_km: float = Field(alias="priceForOneSquareKm", description="USD")
    price_for_one_square_km_cents: int | None = Field(
        default=None, alias="priceForOneSquareKmCents"
    )
    gsd_deg_min: float = Field(alias="gsdDegMin")
    gsd_deg_max: float = Field(alias="gsdDegMax")


class PassPredictionResponse(BaseModel):
    """Response from POST /feasibility/pass-prediction."""

    model_config = ConfigDict(extra="ignore")

    passes: list[Pass]


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


class TaskingOrderRequest(BaseModel):
    """Request body for POST /order-tasking."""

    aoi: str = Field(description="WKT POLYGON")
    window_start: datetime = Field(alias="windowStart")
    window_end: datetime = Field(alias="windowEnd")
    product_type: ProductType = Field(alias="productType")
    resolution: str
    delivery_driver: DeliveryDriver = Field(default=DeliveryDriver.NONE, alias="deliveryDriver")
    delivery_params: dict[str, Any] | None = Field(default=None, alias="deliveryParams")
    label: str = Field(default="Platform Order")
    order_label: str = Field(default="Platform Order", alias="orderLabel")
    metadata: dict[str, Any] | None = None
    webhook_url: str | None = Field(default=None, alias="webhookUrl")
    priority_item: bool = Field(default=False, alias="priorityItem")
    max_cloud_coverage_percent: int | None = Field(
        default=20, alias="maxCloudCoveragePercent"
    )
    max_off_nadir_angle: int | None = Field(default=30, alias="maxOffNadirAngle")
    required_provider: ApiProvider | None = Field(default=None, alias="requiredProvider")
    sar_product_types: list[SarProductType] | None = Field(
        default=None, alias="sarProductTypes"
    )
    sar_polarisation: SarPolarisation | None = Field(default=None, alias="sarPolarisation")
    sar_grazing_angle_min: float | None = Field(default=None, alias="sarGrazingAngleMin")
    sar_grazing_angle_max: float | None = Field(default=None, alias="sarGrazingAngleMax")
    sar_azimuth_angle_min: float | None = Field(default=None, alias="sarAzimuthAngleMin")
    sar_azimuth_angle_max: float | None = Field(default=None, alias="sarAzimuthAngleMax")
    sar_number_of_looks: int | None = Field(default=None, alias="sarNumberOfLooks")
    provider_window_id: uuid.UUID | None = Field(default=None, alias="providerWindowId")

    model_config = ConfigDict(populate_by_name=True)

    def model_dump_skyfi(self) -> dict[str, Any]:
        """Serialize for SkyFi API.

        Omits deliveryDriver/deliveryParams when driver is NONE — SkyFi's API
        does not accept "NONE" as a driver value; the field must be absent.
        """
        data = self.model_dump(by_alias=True, exclude_none=True, mode="json")
        if data.get("deliveryDriver") == "NONE":
            data.pop("deliveryDriver", None)
            data.pop("deliveryParams", None)
        return data


class ArchiveOrderRequest(BaseModel):
    """Request body for POST /order-archive."""

    aoi: str = Field(description="WKT POLYGON")
    archive_id: str = Field(alias="archiveId")
    delivery_driver: DeliveryDriver = Field(default=DeliveryDriver.NONE, alias="deliveryDriver")
    delivery_params: dict[str, Any] | None = Field(default=None, alias="deliveryParams")
    label: str = Field(default="Platform Order")
    order_label: str = Field(default="Platform Order", alias="orderLabel")
    metadata: dict[str, Any] | None = None
    webhook_url: str | None = Field(default=None, alias="webhookUrl")

    model_config = ConfigDict(populate_by_name=True)

    def model_dump_skyfi(self) -> dict[str, Any]:
        """Serialize for SkyFi API.

        Omits deliveryDriver/deliveryParams when driver is NONE — SkyFi's API
        does not accept "NONE" as a driver value; the field must be absent.
        """
        data = self.model_dump(by_alias=True, exclude_none=True, mode="json")
        if data.get("deliveryDriver") == "NONE":
            data.pop("deliveryDriver", None)
            data.pop("deliveryParams", None)
        return data


class TaskingOrderResponse(BaseModel):
    """Response from POST /order-tasking or GET /orders/{id} for tasking orders."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: uuid.UUID
    order_id: uuid.UUID = Field(alias="orderId")
    item_id: uuid.UUID = Field(alias="itemId")
    order_type: OrderType = Field(alias="orderType")
    order_cost: int = Field(alias="orderCost", description="Cents")
    owner_id: uuid.UUID = Field(alias="ownerId")
    status: DeliveryStatus
    order_code: str = Field(alias="orderCode")
    created_at: datetime = Field(alias="createdAt")
    aoi: str  # WKT
    aoi_sqkm: float = Field(alias="aoiSqkm")
    window_start: datetime = Field(alias="windowStart")
    window_end: datetime = Field(alias="windowEnd")
    product_type: ProductType = Field(alias="productType")
    resolution: str
    delivery_driver: DeliveryDriver | None = Field(default=None, alias="deliveryDriver")
    label: str | None = None
    order_label: str | None = Field(default=None, alias="orderLabel")
    priority_item: bool | None = Field(default=None, alias="priorityItem")
    max_cloud_coverage_percent: int | None = Field(
        default=None, alias="maxCloudCoveragePercent"
    )
    max_off_nadir_angle: int | None = Field(default=None, alias="maxOffNadirAngle")
    required_provider: ApiProvider | None = Field(default=None, alias="requiredProvider")
    download_image_url: str | None = Field(default=None, alias="downloadImageUrl")
    download_payload_url: str | None = Field(default=None, alias="downloadPayloadUrl")
    download_cog_url: str | None = Field(default=None, alias="downloadCogUrl")
    tiles_url: str | None = Field(default=None, alias="tilesUrl")
    payload_size: int | None = Field(default=None, alias="payloadSize")
    cog_size: int | None = Field(default=None, alias="cogSize")
    geocode_location: str | None = Field(default=None, alias="geocodeLocation")
    deliverable_id: uuid.UUID | None = Field(default=None, alias="deliverableId")
    provider_window_id: uuid.UUID | None = Field(default=None, alias="providerWindowId")
    webhook_url: str | None = Field(default=None, alias="webhookUrl")


class ArchiveOrderResponse(BaseModel):
    """Response from POST /order-archive or GET /orders/{id} for archive orders."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: uuid.UUID
    order_id: uuid.UUID = Field(alias="orderId")
    item_id: uuid.UUID = Field(alias="itemId")
    order_type: OrderType = Field(alias="orderType")
    order_cost: int = Field(alias="orderCost", description="Cents")
    owner_id: uuid.UUID = Field(alias="ownerId")
    status: DeliveryStatus
    order_code: str = Field(alias="orderCode")
    created_at: datetime = Field(alias="createdAt")
    aoi: str  # WKT
    aoi_sqkm: float = Field(alias="aoiSqkm")
    archive_id: str = Field(alias="archiveId")
    archive: Archive
    delivery_driver: DeliveryDriver | None = Field(default=None, alias="deliveryDriver")
    label: str | None = None
    order_label: str | None = Field(default=None, alias="orderLabel")
    download_image_url: str | None = Field(default=None, alias="downloadImageUrl")
    download_payload_url: str | None = Field(default=None, alias="downloadPayloadUrl")
    download_cog_url: str | None = Field(default=None, alias="downloadCogUrl")
    tiles_url: str | None = Field(default=None, alias="tilesUrl")
    payload_size: int | None = Field(default=None, alias="payloadSize")
    cog_size: int | None = Field(default=None, alias="cogSize")
    geocode_location: str | None = Field(default=None, alias="geocodeLocation")
    deliverable_id: uuid.UUID | None = Field(default=None, alias="deliverableId")
    webhook_url: str | None = Field(default=None, alias="webhookUrl")


# Union type for order responses
OrderInfo = TaskingOrderResponse | ArchiveOrderResponse


class ListOrdersResponse(BaseModel):
    """Response from GET /orders."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    total: int
    orders: list[TaskingOrderResponse | ArchiveOrderResponse]


class OrderRedeliveryRequest(BaseModel):
    """Request body for POST /orders/{id}/redelivery."""

    delivery_driver: DeliveryDriver = Field(alias="deliveryDriver")
    delivery_params: dict[str, Any] = Field(alias="deliveryParams")

    model_config = ConfigDict(populate_by_name=True)

    def model_dump_skyfi(self) -> dict[str, Any]:
        """Serialize for SkyFi API."""
        return self.model_dump(by_alias=True, mode="json")


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


class CreateNotificationRequest(BaseModel):
    """Request body for POST /notifications."""

    aoi: str = Field(description="WKT POLYGON")
    webhook_url: str = Field(alias="webhookUrl")
    gsd_min: int | None = Field(default=None, alias="gsdMin")
    gsd_max: int | None = Field(default=None, alias="gsdMax")
    product_type: ProductType | None = Field(default=None, alias="productType")

    model_config = ConfigDict(populate_by_name=True)

    def model_dump_skyfi(self) -> dict[str, Any]:
        """Serialize for SkyFi API."""
        return self.model_dump(by_alias=True, exclude_none=True, mode="json")


class NotificationResponse(BaseModel):
    """A notification monitor."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: uuid.UUID
    owner_id: uuid.UUID = Field(alias="ownerId")
    aoi: str  # WKT
    gsd_min: int | None = Field(default=None, alias="gsdMin")
    gsd_max: int | None = Field(default=None, alias="gsdMax")
    product_type: ProductType | None = Field(default=None, alias="productType")
    webhook_url: str = Field(alias="webhookUrl")
    created_at: datetime = Field(alias="createdAt")


class NotificationWithHistory(BaseModel):
    """A notification with its event history."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: uuid.UUID
    owner_id: uuid.UUID = Field(alias="ownerId")
    aoi: str
    gsd_min: int | None = Field(default=None, alias="gsdMin")
    gsd_max: int | None = Field(default=None, alias="gsdMax")
    product_type: ProductType | None = Field(default=None, alias="productType")
    webhook_url: str = Field(alias="webhookUrl")
    created_at: datetime = Field(alias="createdAt")
    history: list[dict[str, Any]] = Field(default_factory=list)


class ListNotificationsResponse(BaseModel):
    """Response from GET /notifications."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    total: int
    notifications: list[NotificationResponse]


# ---------------------------------------------------------------------------
# Demo delivery
# ---------------------------------------------------------------------------


class DemoDeliveryRequest(BaseModel):
    """Request body for POST /demo-delivery."""

    delivery_driver: DeliveryDriver = Field(alias="deliveryDriver")
    delivery_params: dict[str, Any] = Field(alias="deliveryParams")

    model_config = ConfigDict(populate_by_name=True)

    def model_dump_skyfi(self) -> dict[str, Any]:
        """Serialize for SkyFi API."""
        return self.model_dump(by_alias=True, mode="json")


class DemoDeliveryResponse(BaseModel):
    """Response from POST /demo-delivery."""

    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID


# ---------------------------------------------------------------------------
# Webhook payloads (inbound from SkyFi)
# ---------------------------------------------------------------------------


class DeliveryEventInfo(BaseModel):
    """Order status change event info."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    status: DeliveryStatus
    timestamp: datetime
    message: str | None = None


class OrderInfoWithEvent(BaseModel):
    """Webhook payload: order status change event."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    order_info: TaskingOrderResponse | ArchiveOrderResponse = Field(alias="orderInfo")
    event: DeliveryEventInfo
