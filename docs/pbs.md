# PBS execution

## Purpose

The PBS backend is deliberately a small adapter for researchers who already use
PBS on their HPC system. It does not introduce a scheduler service, an external
database, polling loop or a second workflow language.

A PBS task generates an auditable `job.pbs` script and submits it with:

```bash
qsub -W block=true -V job.pbs
```

The `-W block=true` behavior is essential: `simpleWorkflow` advances only after
the PBS job has reached its final result. The task is therefore marked as
successful only when the underlying job completed successfully, rather than
when it was merely accepted by the queue.

## Example

```yaml
workflow:
  name: monan_analysis

context:
  project_root: /p/projetos/monan_das/user/project
  cycle: 2018041500

tasks:
  - name: analysis
    executor: pbs
    argv:
      - bash
      - wrappers/jaci/run_mpas_jedi.sh
      - --cycle
      - "{cycle}"
    cwd: "{project_root}"
    env:
      OMP_NUM_THREADS: "1"
      FI_CXI_RX_MATCH_MODE: hybrid
    pbs:
      queue: pesqmini
      project: monan_das
      walltime: "00:30:00"
      select: 1
      ncpus: 128
      mpiprocs: 128
      omp_threads: 1
      inherit_environment: true
      block: true
```

The runner creates a PBS script with the corresponding `#PBS` directives and a
shell-escaped `exec` invocation of the task `argv`. The workflow definition
still never accepts a free-form shell command string.

## Supported `pbs` fields

| Field | Default | Meaning |
| --- | --- | --- |
| `queue` | PBS default | Queue passed as `#PBS -q`. |
| `project` | PBS default | Account/project passed as `#PBS -A`. |
| `walltime` | PBS default | Required format: `HHH:MM:SS`. |
| `select` | `1` when CPU resources are set | PBS chunk count. |
| `ncpus` | PBS default | CPUs per selected chunk. |
| `mpiprocs` | PBS default | MPI ranks per selected chunk. |
| `omp_threads` | unset | Exports `OMP_NUM_THREADS` unless explicitly set in `env`. |
| `job_name` | task name | PBS job name. |
| `qsub` | `qsub` | Submission command, useful for site wrappers or tests. |
| `inherit_environment` | `true` | Adds `-V` to export the submission environment. |
| `block` | `true` | Must remain true in this version. |

Non-blocking submission is intentionally rejected. Supporting it correctly
would require a durable scheduler state machine, monitoring, cancellation and
recovery logic; that would violate the project goal of remaining small and easy
to trust.

## Runtime records

For each PBS attempt, the provenance directory contains:

```text
.simpleworkflow/runs/<run-id>/tasks/<task>/attempt-001/
  stdout.log       # qsub command and submission output
  stderr.log       # qsub errors
  job.pbs          # exact rendered PBS script
  pbs.stdout.log   # job stdout requested through PBS
  pbs.stderr.log   # job stderr requested through PBS
  metadata.json    # execution backend, job id, paths and task provenance
```

`metadata.json` deliberately records only the task-declared environment. Even
when `inherit_environment: true` is required by an HPC module setup, inherited
environment variables are not copied into provenance because they may contain
credentials or machine-specific values.

## Site validation checklist

Before using the backend for a scientific baseline, run one small job on the
target system and confirm that:

1. `qsub -W block=true` waits for the job and propagates a non-zero job exit
   status;
2. the compute nodes can see the workflow working directory and the attempt
   directory;
3. PBS honors the requested `-o` and `-e` paths;
4. the intended module/environment setup reaches the job through `-V` or is
   initialized by the explicit task wrapper.

For JACI, keep the HPC environment setup in a versioned wrapper from the
scientific workflow repository. `simpleWorkflow` should only schedule and
record that wrapper invocation.
