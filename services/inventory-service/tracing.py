import os
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ALWAYS_OFF, ParentBased, TraceIdRatioBased
from opentelemetry.sdk.resources import Resource

def _build_sampler():
    # OTEL_TRACES_SAMPLER/OTEL_TRACES_SAMPLER_ARG (Phase 11) - standard OTel
    # env vars, read by hand since this project builds TracerProvider itself.
    name = os.getenv("OTEL_TRACES_SAMPLER", "parentbased_always_on")
    arg = os.getenv("OTEL_TRACES_SAMPLER_ARG")
    ratio = float(arg) if arg else 1.0
    if name == "always_on":
        return ALWAYS_ON
    if name == "always_off":
        return ALWAYS_OFF
    if name == "traceidratio":
        return TraceIdRatioBased(ratio)
    if name == "parentbased_always_off":
        return ParentBased(ALWAYS_OFF)
    if name == "parentbased_traceidratio":
        return ParentBased(TraceIdRatioBased(ratio))
    return ParentBased(ALWAYS_ON)
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

def setup_tracing(app: FastAPI, service_name: str):
    # Setup Resource and Tracer Provider
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource, sampler=_build_sampler())
    trace.set_tracer_provider(provider)

    # Setup OTLP Exporter
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
    exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
    processor = BatchSpanProcessor(exporter)
    provider.add_span_processor(processor)

    # Instrument FastAPI
    FastAPIInstrumentor.instrument_app(app)

    # Instrument SQLAlchemy (globally)
    try:
        SQLAlchemyInstrumentor().instrument()
    except Exception:
        pass # Ignore if SQLAlchemy is not used or already instrumented
