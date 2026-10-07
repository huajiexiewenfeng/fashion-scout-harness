import io
import json
from urllib.parse import parse_qs
import httpx
from PIL import Image
from fashion_scout.config import Paths
from fashion_scout.db import Database
from fashion_scout.domain import CreateRun
from fashion_scout.domain.models import DefaultPlan, Discovery, Network, Storage
from fashion_scout.services.runs import Runs
from fashion_scout.services.collect import Collector
from fashion_scout.worker import Worker


def png(color="red"):
    output = io.BytesIO()
    Image.new("RGB", (8, 9), color).save(output, "PNG")
    return output.getvalue()


def product(identifier="1", date="2026-10-05T12:00:00Z", images=1):
    return {"id": int(identifier), "handle": "item-" + identifier, "title": "Synthetic",
            "published_at": date, "created_at": "2025-01-01T00:00:00Z", "product_type": "Dresses",
            "variants": [{"id": int(identifier)*10, "option1": "Red", "featured_image": {"id": int(identifier)*100, "src": f"https://cdn.shopify.com/{identifier}-0.png"}}],
            "options": [{"name": "Color", "values": ["Red"]}],
            "images": [{"id": int(identifier)*100+i, "src": f"https://cdn.shopify.com/{identifier}-{i}.png"} for i in range(images)]}


class Scenario:
    def __init__(self, products, page_size=2):
        self.products, self.page_size = products, page_size
        self.calls, self.image_data, self.statuses, self.pages = [], {}, {}, None

    def handler(self, request):
        self.calls.append(str(request.url))
        if request.url.host == "cdn.shopify.com":
            data = self.image_data.get(request.url.path, png())
            return httpx.Response(self.statuses.get(request.url.path, 200), stream=httpx.ByteStream(data))
        if request.url.path.endswith("/products.json"):
            page = int(parse_qs(request.url.query.decode())["page"][0])
            items = self.pages(page) if self.pages else self.products[(page-1)*self.page_size:page*self.page_size]
            return httpx.Response(200, stream=httpx.ByteStream(json.dumps({"products": items}).encode()))
        if request.url.path.endswith(".js"):
            handle = request.url.path.rsplit("/", 1)[1][:-3]
            return httpx.Response(200, stream=httpx.ByteStream(json.dumps(next(p for p in self.products if p["handle"] == handle)).encode()))
        raise AssertionError(str(request.url))

    def transport(self, deadline):
        return httpx.MockTransport(self.handler)


def setup(tmp_path, **changes):
    paths = Paths.at(tmp_path)
    paths.prepare()
    runs = Runs(Database(paths.db))
    runs.initialize()
    plan = DefaultPlan(discovery=Discovery(page_size=2, max_pages_per_pass=5),
        network=Network(min_interval_ms=1), storage=Storage(min_free_bytes=1, max_pixels=10000, max_image_bytes=1048576))
    plan = plan.model_copy(update=changes)
    runs.save_default(plan, 1)
    return runs, paths


def accept(runs, key="first"):
    return runs.create(CreateRun(request_key=key, trigger="ui")).run


def execute(runs, paths, run_id, scenario, before=None):
    errors = []
    def executor(ctx):
        try:
            if before:
                before(ctx)
            return Collector(ctx, transport_factory=scenario.transport, sleep=lambda n: None).run()
        except Exception as exc:
            errors.append(exc)
            raise
    Worker(paths, lambda: runs.get(run_id).state in ("succeeded", "failed", "partial", "cancelled"),
           executor=executor, heartbeat_seconds=0.1, lease_seconds=15).run()
    if errors:
        raise errors[0]
    return runs.get(run_id)
