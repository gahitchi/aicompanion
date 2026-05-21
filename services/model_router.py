class ModelRouter:

    def __init__(self):

        self.models = {
            "fast": "qwen2.5:7b-instruct",
            "smart": "llama3:8b",
            "reasoning": "mixtral:8x7b"
        }


    def select(self, task_type):

        if task_type == "reasoning":
            return self.models["reasoning"]

        if task_type == "fast":
            return self.models["fast"]

        return self.models["smart"]