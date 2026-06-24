# Ciclos temporais

Um workflow pode documentar uma sequência temporal opcional sem tornar as tarefas mais complexas:

```yaml
cycle:
  start: 2018-04-15T00:00:00Z
  end: 2018-04-30T18:00:00Z
  step: PT6H
```

O motor adiciona `{cycle_time}` e `{cycle_id}` ao contexto de cada instância. Cada ciclo mantém estado, logs e tentativas próprios em `.simpleworkflow/cycles/<cycle-id>/`.

Os valores documentados podem ser substituídos pela linha de comando:

```bash
simpleworkflow run workflow.yaml \
  --from 2018-04-20T00:00:00Z \
  --to 2018-04-22T18:00:00Z \
  --step PT6H
```

Para executar apenas um instante:

```bash
simpleworkflow run workflow.yaml --cycle-time 2018-04-21T00:00:00Z
```

A precedência é: opções da linha de comando, valores do YAML e execução única. Ao repetir o comando, tarefas concluídas e válidas são reaproveitadas dentro de cada ciclo; uma falha interrompe a sequência e preserva o estado para retomada posterior.
