# Reproducing a published result

Start in the repository root with the harness installed. A [results card](results/index/recommended/README.md) identifies the hardware, experiment and source report. Pick one job from the report. A campaign can contain several models and harnesses.

## Find the recorded inputs

This worked example is the published WSL2 LM Studio run of Inkling 2 Mini IQ4_NL. These inspection commands need no accelerator, model downloads or credentials.

```bash
bundle=docs/results/hardware-fit/campaign-20261124T232244Z-86c68e03-fit-hardware-fit-1
job=fit-hardware-fit-1-971aedbccee6
llm-eval verify-results
llm-eval result-inputs --input "$bundle"
llm-eval result-inputs --input "$bundle" --job "$job"
```

The first inspection lists the case and job IDs. The second reports the measured harness commit, hardware, runtime, settings, suite hashes and artifact lock. With the example above, the reported weight file is `Inkling-2-Mini-IQ4_NL.gguf`, 17,627,940,768 bytes. The source is `ggml-org/Inkling-2-Mini-GGUF` at `e8a2cecf0e78914f07cc27b9be711a9b2c7561d9`. The experiment used LM Studio `0.4.28+2`, an 8,192-token context setting and a 2,048-token output cap. See the [original report](results/hardware-fit/campaign-20261124T232244Z-86c68e03-fit-hardware-fit-1/README.md).

After obtaining the exact named files, point the command to the directory containing only that artifact variant. It reads and hashes every recorded file and checks the inventory. Save the successful output as input to reconstruction.

```bash
llm-eval result-inputs --input "$bundle" --job "$job" --artifact-dir "$ARTIFACT_ROOT" > replica-inputs.json
```

Empty artifact or suite lists mean the public job did not supply this evidence. Decision-only runs identify a router and its recorded model revision. Public legal reports expose the reviewed cohort digests and execution class. Use the [legal walkthrough](LEGAL_MODELS_WALKTHROUGH.md) for the approved fictional suite, local serving qualification and manual review.

## Rebuild the measured case

1. **Use a separate checkout for the measurement.** Keep the checkout containing this reporting tool available. From a full clone, the following command creates a second checkout of the measured code for this example.

   ```bash
   git worktree add --detach ../llm-eval-replica ce08c168fac5bbd7eff09b8356c036c35e7ce106
   ```

2. **Bind local inputs.** In the measured checkout, use the [WSL2 walkthrough](WSL_RAIDER_WALKTHROUGH.md) to prepare the inventory, shared host lock and installed engine state. Select the source job in the published `resolved-config.json`. Its `parameters` contain the case and run settings. Copy those into your local case; replace the omitted artifact root, lock, suite, endpoint and offload paths. The case in this example uses `server_mode: managed`, the `hardware-fit` measured mode, the LM Studio harness, and categories `reasoning`, `coding`, `math` in their recorded order. Write the `lock` object from the verified `artifact_locks` entry as the local artifact lock, outside the model directory. Use the recorded file, template and launch settings. Supply your own hardware attestation and identify any differences from the reference.
3. **Plan one job and inspect it.** Select only that case and hardware ID in the local campaign. Keep publication disabled for the first run. In the measured checkout's environment, run the normal campaign commands.

   ```bash
   llm-eval plan --campaign configs/local/replica/campaign.json
   llm-eval setup --campaign configs/local/replica/campaign.json
   llm-eval run --campaign configs/local/replica/campaign.json --max-parallel-jobs 1
   ```

4. **Compare the evidence.** Check artifact files, task hashes, output cap, template, runtime, actual token lengths, power mode and placement evidence. For this reference, 27 checks came from nine prompts, each repeated three times. The LM Studio report inferred residency from device-wide GPU memory. A run on another OS, power mode, placement method or device is valuable as a declared variant. Follow the [submission instructions](../CONTRIBUTING.md) to contribute a confirmation, a conflicting result or a documented failure.
