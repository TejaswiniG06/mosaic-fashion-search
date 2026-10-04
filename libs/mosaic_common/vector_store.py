"""Qdrant wrapper: one collection, two named vectors (text 384-d e5, image 512-d CLIP), product
payload with indexed filter fields so hard constraints are pushed down into the ANN search."""
from __future__ import annotations

import uuid
from typing import Any

from qdrant_client import AsyncQdrantClient, models as qm

from .filters import FREE_SIZE
from .schemas import HardFilters

NS = uuid.UUID("6f1c3d1e-6a43-4b6b-9a77-0c1d9f6c2a11")


def point_id(asin: str) -> str:
    return str(uuid.uuid5(NS, asin))


class VectorStore:
    def __init__(self, url: str, collection: str, api_key: str | None = None):
        # gRPC transport: ~3-5x cheaper (de)serialisation of vectors than REST/JSON
        self.client = AsyncQdrantClient(url=url, api_key=api_key, timeout=10, check_compatibility=False, prefer_grpc=True)
        self.collection = collection

    async def ensure_collection(self) -> None:
        if await self.client.collection_exists(self.collection):
            return
        await self.client.create_collection(
            self.collection,
            vectors_config={"text": qm.VectorParams(size=384, distance=qm.Distance.COSINE),
                            "image": qm.VectorParams(size=512, distance=qm.Distance.COSINE)},
            hnsw_config=qm.HnswConfigDiff(m=16, ef_construct=128),
            optimizers_config=qm.OptimizersConfigDiff(indexing_threshold=10000),
        )
        for field, schema in (("price", qm.PayloadSchemaType.FLOAT), ("stock_qty", qm.PayloadSchemaType.INTEGER),
                              ("sizes", qm.PayloadSchemaType.KEYWORD), ("attributes.category", qm.PayloadSchemaType.KEYWORD),
                              ("attributes.gender", qm.PayloadSchemaType.KEYWORD), ("parent_asin", qm.PayloadSchemaType.KEYWORD)):
            await self.client.create_payload_index(self.collection, field, field_schema=schema)

    @staticmethod
    def build_filter(f: HardFilters) -> qm.Filter | None:
        must: list[Any] = []
        if f.price_max is not None or f.price_min is not None:
            must.append(qm.FieldCondition(key="price", range=qm.Range(lte=f.price_max, gte=f.price_min)))
        if f.in_stock_only:
            must.append(qm.FieldCondition(key="stock_qty", range=qm.Range(gt=0)))
        if f.size:
            must.append(qm.FieldCondition(key="sizes", match=qm.MatchAny(any=[f.size.upper(), f.size, FREE_SIZE])))
        if f.categories:
            must.append(qm.FieldCondition(key="attributes.category", match=qm.MatchAny(any=f.categories)))
        if f.gender:
            must.append(qm.FieldCondition(key="attributes.gender", match=qm.MatchAny(any=[f.gender, "unisex"])))
        return qm.Filter(must=must) if must else None

    async def upsert(self, items: list[tuple[str, dict[str, Any], list[float], list[float] | None]]) -> None:
        points = []
        for asin, payload, tvec, ivec in items:
            vec: dict[str, list[float]] = {"text": tvec}
            if ivec is not None:
                vec["image"] = ivec
            points.append(qm.PointStruct(id=point_id(asin), vector=vec, payload={**payload, "has_image": ivec is not None}))
        if points:
            await self.client.upsert(self.collection, points=points, wait=True)

    async def delete(self, asins: list[str]) -> None:
        if asins:
            await self.client.delete(self.collection, points_selector=qm.PointIdsList(points=[point_id(a) for a in asins]), wait=True)

    async def search(self, vector: list[float], using: str, f: HardFilters, limit: int, ef: int = 128,
                     with_vectors: list[str] | None = None) -> list[tuple[str, float, dict, dict]]:
        res = await self.client.query_points(self.collection, query=vector, using=using, query_filter=self.build_filter(f), limit=limit,
                                             with_payload=True, with_vectors=with_vectors or False, search_params=qm.SearchParams(hnsw_ef=ef))
        return [(p.payload["parent_asin"], float(p.score), p.payload, (p.vector or {}) if with_vectors else {}) for p in res.points]

    async def vectors(self, asins: list[str], names: list[str]) -> dict[str, dict[str, list[float]]]:
        if not asins:
            return {}
        pts = await self.client.retrieve(self.collection, ids=[point_id(a) for a in asins], with_vectors=names, with_payload=["parent_asin"])
        return {p.payload["parent_asin"]: (p.vector or {}) for p in pts}

    async def count(self) -> int:
        return (await self.client.count(self.collection, exact=False)).count
