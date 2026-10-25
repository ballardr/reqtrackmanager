"""
Package: services.perf_dataset

Bulk dataset generation for the performance tooling (`perf/`): scales every record type, and the links between
them, to a chosen tier so scaling problems show up in measurements. See `build.generate_dataset` for the entry
point and `modules.registry.PerfDatasetGenerator` for how a module adds its own record types.
"""
