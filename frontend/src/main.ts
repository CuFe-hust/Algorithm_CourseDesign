import { createApp } from "vue";
import App from "./App.vue";
import router from "./app/router";
import "./styles.css";
import "./workspace.css";

createApp(App).use(router).mount("#app");
