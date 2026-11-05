declare module "@novnc/novnc" {
  export default class RFB {
    constructor(target: HTMLElement, url: string);
    scaleViewport: boolean;
    resizeSession: boolean;
    background: string;
    focus(): void;
    disconnect(): void;
    addEventListener(type: string, listener: (event: Event) => void): void;
  }
}
