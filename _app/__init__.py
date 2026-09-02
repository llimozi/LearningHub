# -*- coding: utf-8 -*-
"""_app 包: LearningHub 内部实现包（Phase 2 渐进式重构产物）。

模块依赖方向(严格单向 DAG):
  config -> paths(外部)
  data / utils -> config
  services -> data / utils / config
  api -> services / data / utils / config
  renderer -> services / data / utils / config   (render 开头绑定 _app 依赖为局部变量)
  server -> api / services / data / config       (render 延迟导入 build_dashboard, 避免循环)
  build_dashboard(根) -> 仅 re-export + 入口(main/selftest), 零业务逻辑
"""
