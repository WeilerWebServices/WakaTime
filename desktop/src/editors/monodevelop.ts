import os from 'os';
import path from 'path';

import Editor from './editor';

export default class MonoDevelop extends Editor {
  public static getName(): string {
    return 'MonoDevelop';
  }

  public get name(): string {
    return 'MonoDevelop';
  }

  public get icon(): string {
    return '';
  }

  public async isEditorInstalled(): Promise<boolean> {
    return this.isDirectory(this.appDirectory());
  }

  public async isPluginInstalled(): Promise<boolean> {
    return this.isDirectory(this.pluginsDirectory());
  }

  public async installPlugin(): Promise<void> {
    throw new Error('Method not implemented.');
  }

  public async uninstallPlugin(): Promise<void> {
    throw new Error('Method not implemented.');
  }

  public pluginsDirectory(): string {
    switch (os.platform()) {
      case 'win32': {
        return '';
      }
      case 'darwin': {
        return ''; // return empty because MonoDevelop is not available in mac
      }
      case 'linux':
        return '';
      default:
        return null;
    }
  }

  public appDirectory(): string {
    switch (os.platform()) {
      case 'win32':
        return '';
      case 'darwin':
        return ''; // return empty because MonoDevelop is not available in mac
      default:
        return null;
    }
  }
}
