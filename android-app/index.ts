import { registerRootComponent } from 'expo';
import { registerHeadless } from './src/headless';
import App from './App';

registerHeadless(); // must be registered at module load so Android can start it with the app closed
registerRootComponent(App);
