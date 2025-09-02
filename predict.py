import torch
import pandas as pd
import joblib
class ECGNet(torch.nn.Module):
    def __init__(self, input_size, num_classes):
        super(ECGNet, self).__init__()
        self.fc1 = torch.nn.Linear(input_size, 128)
        self.relu1 = torch.nn.ReLU()
        self.fc2 = torch.nn.Linear(128, 64)
        self.relu2 = torch.nn.ReLU()
        self.fc3 = torch.nn.Linear(64, num_classes)

    def forward(self, x):
        x = self.relu1(self.fc1(x))
        x = self.relu2(self.fc2(x))
        return self.fc3(x)

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = ECGNet(input_size=187, num_classes=5)  
model.load_state_dict(torch.load("data/ecg_model_mlp.pth", map_location=device))
model.to(device)
model.eval()

scaler = joblib.load("data/minmaxscaler.pkl")

new_data = pd.read_csv("ecg_segmentado_187.csv", header=None, sep=';')

if new_data.shape[1] == 0:
    raise ValueError("CSV FILE IS EMPTY")

X_new = new_data.values  
X_new_scaled = scaler.transform(X_new)

X_new_tensor = torch.tensor(X_new_scaled, dtype=torch.float32).to(device)

with torch.no_grad():
    outputs = model(X_new_tensor)
    _, predicted_classes = torch.max(outputs, 1)

new_data['Predicted_Class'] = predicted_classes.cpu().numpy()

new_data.to_csv("predicted_data.csv", index=False)
