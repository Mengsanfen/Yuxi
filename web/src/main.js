import { createApp } from 'vue'
import { createPinia } from 'pinia'
import piniaPluginPersistedstate from 'pinia-plugin-persistedstate'

import App from './App.vue'
import router from './router'

import {
  Alert,
  Avatar,
  Badge,
  Button,
  Card,
  Checkbox,
  Col,
  Collapse,
  ConfigProvider,
  DatePicker,
  Descriptions,
  Divider,
  Dropdown,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Menu,
  Modal,
  Popconfirm,
  Popover,
  Progress,
  Radio,
  Result,
  Row,
  Segmented,
  Select,
  Skeleton,
  Slider,
  Space,
  Spin,
  Statistic,
  Switch,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Tree,
  TreeSelect,
  Upload
} from 'ant-design-vue'
import 'ant-design-vue/dist/reset.css'
import '@/assets/css/main.css'

const app = createApp(App)
const pinia = createPinia()
pinia.use(piniaPluginPersistedstate)

app.use(pinia)
app.use(router)

const antDesignComponents = [
  Alert,
  Avatar,
  Badge,
  Button,
  Card,
  Checkbox,
  Col,
  Collapse,
  ConfigProvider,
  DatePicker,
  Descriptions,
  Divider,
  Dropdown,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Menu,
  Modal,
  Popconfirm,
  Popover,
  Progress,
  Radio,
  Result,
  Row,
  Segmented,
  Select,
  Skeleton,
  Slider,
  Space,
  Spin,
  Statistic,
  Switch,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Tree,
  TreeSelect,
  Upload
]
antDesignComponents.forEach((component) => app.use(component))

// 预加载信息配置
import { useInfoStore } from '@/stores/info'
const infoStore = useInfoStore()
infoStore.loadInfoConfig()

app.mount('#app')
