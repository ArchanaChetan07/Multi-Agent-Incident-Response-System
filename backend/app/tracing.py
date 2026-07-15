"""Phase 4: OpenTelemetry instrumentation.

Exports to console by default (zero-dependency demo). Swap ConsoleSpanExporter
for OTLPSpanExporter pointed at Jaeger/Tempo in production (see README).
"""
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource

_resource = Resource(attributes={"service.name": "incident-response-system"})
_provider = TracerProvider(resource=_resource)
_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(_provider)

tracer = trace.get_tracer("incident-response-system")
