# 统一前端目录约定

状态：前端开发位置已约定，当前没有可启动的Vue应用。教师Issue的T00先交共同骨架，学生负责人同时准备功能组件；分析负责人不依赖前端完成后台流程。

## T00需要建立的结构

```text
frontend/
  package.json、依赖锁、Vite/TypeScript配置
  src/
    main.ts、App.vue
    app/                 登录、课程选择、布局与路由
    shared/api/          统一HTTP客户端、Bearer和错误处理
    shared/components/   通用加载、空状态、错误展示
    features/teacher/    T负责
    features/student/    S负责
    features/analytics/  A负责
```

使用Vue 3/TypeScript/Vite，开发端口5173；API默认127.0.0.1:8000/api/v1。登录后查courses取得当前课程角色，页面权限以课程为单位；后端仍做最终校验。

该目录已有说明，初始化时保留文档和其他成员已有组件，不通过清空目录解决脚手架冲突。根仓库只有一个frontend，不生成teacher-web/student-web两个独立工程。

所有请求复用shared/api；ID不转Number，分数保留十进制字符串直到显示，UTC时间在界面格式化。token通过Authorization传递，不进URL/日志；前端登录存储与刷新策略由T00和S共同定，401清理身份并提示重登。

Markdown和LaTeX安全渲染；data/demo及data/source含教师参考，不放到public目录、不打包到学生静态资源。mock fixture按规划DTO放在模块内并标记，默认集成使用真实API，不能把404当成功空数据。

具体格式见 [当前API](../docs/API.md)，后续接口见 [规划契约](../docs/contracts/next-phase.md)。
