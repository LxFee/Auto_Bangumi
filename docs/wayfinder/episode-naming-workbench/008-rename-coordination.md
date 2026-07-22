---
title: 确定自动与手动重命名的并发协调
status: open
labels:
  - wayfinder:grilling
parent: ./map.md
blocked_by: []
---

# 确定自动与手动重命名的并发协调

## Question

定时重命名器、用户立即应用和失败重试同时发现同一命名单元时，如何只让一个执行者推进当前已确认修订，并阻止过期修订在用户再次编辑后继续改名？
