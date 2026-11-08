"""Dedicated difficulty-model contracts; B0 and historical snapshots remain unchanged."""
from typing import Literal
from pydantic import Field, model_validator
from .contracts import Contract, Ratio
from .ability_contracts import AbilityInputV2, AbilityEstimate, Nonempty


class ModelParameters(Contract):
    learner_l2: float = Field(default=1.0,gt=0,le=100,allow_inf_nan=False)
    item_l2: float = Field(default=4.0,gt=0,le=100,allow_inf_nan=False)
    difficulty_scale: float = Field(default=.75,ge=0,le=3,allow_inf_nan=False)
    max_iterations: int = Field(default=60,ge=1,le=300)
    tolerance: float = Field(default=1e-6,gt=0,le=.01,allow_inf_nan=False)
    calibrate_items: bool = True


class ProcessEvent(Contract):
    student_key: Nonempty
    item_key: Nonempty
    sequence_no: int = Field(ge=1)
    verdict: Literal['CE','WA','TLE','RE','AC']
    score: Ratio | None = None


class DifficultyInputV1(Contract):
    learning_input: AbilityInputV2
    model_parameters: ModelParameters = Field(default_factory=ModelParameters)
    processes: list[ProcessEvent] = Field(default_factory=list,max_length=100000)

    @model_validator(mode='after')
    def references(self):
        pairs={(p.student_key,p.item_key) for p in self.learning_input.scope.expected_pairs}
        if len(self.learning_input.grades)>40000 or len(self.learning_input.items)>2000:
            raise ValueError('DIFFICULTY_SCOPE_TOO_LARGE')
        seen=set()
        for e in self.processes:
            if (e.student_key,e.item_key) not in pairs:
                raise ValueError('PROCESS_OUTSIDE_SCOPE')
            key=e.student_key,e.item_key,e.sequence_no
            if key in seen:raise ValueError('DUPLICATE_PROCESS_EVENT')
            seen.add(key)
        return self


class DifficultyEstimate(AbilityEstimate):
    baseline_value: Ratio | None
    theta: float | None = Field(default=None,allow_inf_nan=False)
    score_semantics: Literal['REFERENCE_EXPECTED_SCORE'] = 'REFERENCE_EXPECTED_SCORE'


class DifficultyOutputV1(Contract):
    contract_version: Literal['ability-difficulty-v1'] = 'ability-difficulty-v1'
    implementation_version: Literal['2'] = '2'
    source_kind: str
    results_snapshot_version: str
    scoring_policy_version: str
    chapter_taxonomy_version: str
    chapter_mapping_version: str
    method: Literal['DIFFICULTY_FRACTIONAL'] = 'DIFFICULTY_FRACTIONAL'
    model_parameters: ModelParameters
    model_diagnostics: dict
    estimates: list[DifficultyEstimate]
    process_diagnostics: list[dict] = Field(default_factory=list)
