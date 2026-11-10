export declare const HEADLESS_TASK = 'HBNotification';
export declare type PermissionStatus = 'authorized' | 'denied' | 'unavailable';
export declare function getPermissionStatus(): Promise<PermissionStatus>;
export declare function requestPermission(): void;
export declare function setAllowedPackages(pkgs: string[]): void;
export declare function isIgnoringBatteryOptimizations(): Promise<boolean>;
export declare function requestIgnoreBatteryOptimizations(): void;
/** Shape of the JSON string passed to the headless task as `{ notification }`. */
export interface ForwardedNotification { time: string; app: string; title: string; text: string; bigText: string; subText: string; }
