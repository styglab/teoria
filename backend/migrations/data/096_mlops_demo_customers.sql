-- Opt-in demo rows are seeded by the model_operations feature, never by migration.
CREATE SCHEMA IF NOT EXISTS mlops_demo;
COMMENT ON SCHEMA mlops_demo IS '합성 고객 데이터와 MLOps 검증 전용. 실제 개인정보를 저장하지 않는다.';
CREATE TABLE mlops_demo.customers (
    dataset_version text NOT NULL,
    customer_id text NOT NULL,
    full_name text NOT NULL,
    email text NOT NULL CHECK (email LIKE '%@example.invalid'),
    phone text NOT NULL CHECK (phone LIKE '010-XXXX-%'),
    birth_date date NOT NULL,
    address text NOT NULL,
    annual_income integer NOT NULL,
    credit_score integer NOT NULL,
    marketing_consent boolean NOT NULL,
    is_synthetic boolean NOT NULL DEFAULT true CHECK (is_synthetic),
    PRIMARY KEY (dataset_version, customer_id)
);
COMMENT ON TABLE mlops_demo.customers IS '가상 고객 개인정보 형태의 합성 데이터. AI 메타데이터·개방 적합성 진단을 위한 예제이며 실제 고객이나 운영 의사결정에 사용하지 않는다.';
COMMENT ON COLUMN mlops_demo.customers.full_name IS '실존 인물을 지칭하지 않는 가상고객 이름';
COMMENT ON COLUMN mlops_demo.customers.email IS '발송 불가능한 example.invalid 도메인의 합성 이메일';
COMMENT ON COLUMN mlops_demo.customers.phone IS '중간 번호를 XXXX로 고정한 합성 전화번호';
COMMENT ON COLUMN mlops_demo.customers.birth_date IS '가상 생년월일';
COMMENT ON COLUMN mlops_demo.customers.address IS '실재하지 않는 가상시·가상구 주소';
COMMENT ON COLUMN mlops_demo.customers.annual_income IS '가상 연소득(원). 재무정보 분류 검토용';
COMMENT ON COLUMN mlops_demo.customers.credit_score IS '가상 신용점수. 재무정보 분류 검토용';
CREATE TABLE mlops_demo.customer_activity (
    dataset_version text NOT NULL,
    customer_id text NOT NULL,
    tenure_months integer NOT NULL CHECK (tenure_months BETWEEN 1 AND 72),
    monthly_spend numeric(10,2) NOT NULL CHECK (monthly_spend >= 0),
    login_days_30d integer NOT NULL CHECK (login_days_30d BETWEEN 0 AND 30),
    support_tickets_30d integer NOT NULL CHECK (support_tickets_30d BETWEEN 0 AND 12),
    churned boolean NOT NULL,
    is_synthetic boolean NOT NULL DEFAULT true CHECK (is_synthetic),
    PRIMARY KEY (dataset_version, customer_id),
    FOREIGN KEY (dataset_version, customer_id) REFERENCES mlops_demo.customers
);
COMMENT ON TABLE mlops_demo.customer_activity IS '합성 고객의 이용 이력과 가상 이탈 라벨. 고객 단위 학습·검증 분리를 사용하는 MLOps 예제';
COMMENT ON COLUMN mlops_demo.customer_activity.churned IS '합성 확률식으로 생성한 가상 이탈 여부. 실제 고객 관찰값이 아니다';
GRANT USAGE ON SCHEMA mlops_demo TO teoria_metadata;
GRANT SELECT ON ALL TABLES IN SCHEMA mlops_demo TO teoria_metadata;
