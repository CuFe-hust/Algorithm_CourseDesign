from app.analysis.framework.contracts import digest
from app.analysis.framework.catalog import PLUGINS,invoke
from scripts.export_analysis_contracts import build_examples


def test_every_plugin_has_reproducible_input_output_example():
    examples=build_examples()
    assert set(examples)==set(PLUGINS)
    for key,example in examples.items():
        data=example['input']
        assert digest(data['payload'])==data['input_hash']
        result=invoke(key,data['payload'],mode='DEMO',seed=data['seed'],input_hash=data['input_hash'])
        assert result.model_dump(mode='json')==example['output']
        assert example['output']['is_mock']
