"""Frozen property identifiers for historical server-rule artifacts."""

META = {
    "inventory_declared_quantity": (
        "명시 공급·구성 목록 수량",
        "explicit_target",
        "count",
    ),
    "component_quantity_requirement": (
        "구성 대상 수량 요구",
        "hardware_component",
        "count",
    ),
    "cpu_model": ("CPU 모델 요구", "processor", "identifier"),
    "cpu_family": ("CPU 제품군 요구", "processor", "identifier_options"),
    "cpu_pcie_capability": ("CPU PCIe 지원 규격", "processor", "text"),
    "cpu_supported_memory_type": ("CPU 지원 메모리 규격", "processor", "text"),
    "cpu_cores_per_processor": ("CPU당 코어 수", "processor", "integer"),
    "cpu_total_cores": ("시스템 전체 CPU 코어 수", "processor_set", "integer"),
    "cpu_thread_count": ("CPU 스레드 수", "processor", "integer"),
    "cpu_max_clock": ("CPU 최대·부스트 클럭", "processor", "quantity"),
    "cpu_l3_cache_capacity": ("CPU L3 캐시 용량", "processor", "quantity"),
    "cpu_cache_capacity_unspecified_level": (
        "CPU 캐시 용량 — 레벨 미명시",
        "processor",
        "quantity",
    ),
    "cpu_supported_memory_transfer_rate": (
        "CPU 메모리 컨트롤러 지원 전송률",
        "processor",
        "quantity",
    ),
    "memory_module_capacity": ("메모리 모듈당 용량", "memory_module", "quantity"),
    "memory_total_capacity": ("시스템 총 메모리 용량", "memory_set", "quantity"),
    "memory_generation": ("DDR 메모리 세대", "memory", "identifier"),
    "memory_module_form": ("메모리 모듈 형태", "memory_module", "identifier"),
    "memory_composite_specification": ("메모리 복합 규격 원문", "memory", "text"),
    "memory_ecc": ("메모리 오류정정 규격 요구", "memory", "text"),
    "memory_transfer_rate": ("메모리 전송률", "memory", "quantity"),
    "memory_clock_frequency": (
        "메모리 클럭 주파수 — 원문 단위 기준",
        "memory",
        "quantity",
    ),
    "memory_supported_capacity": (
        "확장·지원 가능한 메모리 용량",
        "memory_slot",
        "quantity",
    ),
    "gpu_model": ("GPU 모델", "gpu", "identifier"),
    "gpu_supported_model_options": (
        "지원 가능한 GPU 모델 선택지",
        "gpu",
        "identifier_options",
    ),
    "gpu_memory_capacity": ("GPU 메모리 용량", "gpu", "quantity"),
    "gpu_memory_type": ("GPU 메모리 규격", "gpu", "identifier"),
    "gpu_cuda_cores": ("GPU CUDA 코어 수", "gpu", "integer"),
    "gpu_tensor_cores": ("GPU Tensor 코어 수", "gpu", "integer"),
    "drive_capacity": ("개별 드라이브 용량 요구", "drive", "quantity"),
    "storage_capacity": (
        "스토리지 시스템 용량 — raw/usable 미명시",
        "storage_system",
        "quantity",
    ),
    "storage_raw_capacity": ("스토리지 전체 raw 용량", "storage_system", "quantity"),
    "tape_capacity_specification": ("테이프 복합 용량 원문", "tape_media", "text"),
    "drive_protocol": ("드라이브 접속 프로토콜", "drive", "identifier"),
    "drive_connection_specification": ("드라이브 복합 접속 규격", "drive", "text"),
    "drive_bay_connection_specification": ("베이 지원 접속 규격", "drive_bay", "text"),
    "storage_object_api": ("객체 스토리지 API", "storage_system", "identifier"),
    "drive_link_speed": ("드라이브 데이터 링크 속도", "drive", "quantity"),
    "drive_rotation_speed": ("드라이브 회전 속도", "drive", "quantity"),
    "drive_media_type": ("드라이브 매체 종류", "drive", "identifier"),
    "drive_flash_type": ("플래시 메모리 기술", "drive", "identifier"),
    "drive_usage_class": ("드라이브 용도·등급", "drive", "text"),
    "network_speed": ("네트워크 포트 속도 요구", "network", "quantity"),
    "controller_cache_capacity": (
        "스토리지 컨트롤러 캐시 용량",
        "storage_controller",
        "quantity",
    ),
    "power_capacity": ("PSU 출력 용량", "power_supply", "quantity"),
    "power_redundancy": ("전원 중복 구성 요구", "power_supply", "text"),
    "chassis_height": ("섀시 랙 장착 높이", "chassis", "quantity"),
    "chassis_form_factor": ("섀시 형태", "chassis", "identifier"),
    "delivery_duration_requirement": (
        "납품·설치 소요 기간 요구",
        "procurement_condition",
        "duration",
    ),
    "delivery_calendar_deadline": ("납품 기한 날짜", "procurement_condition", "date"),
    "delivery_deadline_text": ("납품 기한 조건 원문", "procurement_condition", "text"),
    "warranty_duration": ("보증 기간", "procurement_condition", "duration"),
}


def validate_classification(classification_code):
    if classification_code != "4321150102":
        raise ValueError(
            "server rule set requires computer-server classification 4321150102"
        )
