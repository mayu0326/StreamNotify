
class Stub:
    def __init__(self, *args, **kwargs):
        pass
    def pack(self, *args, **kwargs):
        pass
    def grid(self, *args, **kwargs):
        pass
    def destroy(self):
        pass

class UnifiedSettingsWindow(Stub):
    pass
class TemplateEditorDialog(Stub):
    pass
class BatchScheduleManager(Stub):
    def get_next_scheduled_video(self): return None
class BatchScheduleDialog(Stub):
    pass
class ScheduleViewTab(Stub):
    pass

class MockImageManager:
    def get_image_path(self, *args): return None

def get_image_manager():
    return MockImageManager()

class PluginManager:
    def get_plugin(self, name): return None
