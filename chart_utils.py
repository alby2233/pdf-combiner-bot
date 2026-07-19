import os
import csv
import openpyxl
import matplotlib.pyplot as plt

def read_xlsx(file_path):
    wb = openpyxl.load_workbook(file_path, data_only=True)
    sheet = wb.active
    data = []
    for row in sheet.iter_rows(values_only=True):
        if any(v is not None for v in row):
            data.append(row)
    return data

def read_csv(file_path):
    data = []
    # Try different encodings to handle files created on different OS
    for encoding in ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']:
        try:
            with open(file_path, mode='r', encoding=encoding) as f:
                reader = csv.reader(f)
                for row in reader:
                    data.append(row)
            return data
        except UnicodeDecodeError:
            continue
    raise ValueError("Could not decode the CSV file. Please make sure it is in UTF-8 or standard CSV format.")

def parse_spreadsheet(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    if ext in [".xlsx", ".xls"]:
        raw_rows = read_xlsx(file_path)
    else:
        raw_rows = read_csv(file_path)
        
    if not raw_rows:
        raise ValueError("The sheet contains no data.")
        
    # Clean headers
    headers = []
    for h in raw_rows[0]:
        if h is not None:
            headers.append(str(h).strip())
        else:
            headers.append(f"Column_{len(headers)+1}")
            
    rows = []
    for r in raw_rows[1:]:
        row = [r[i] if i < len(r) else None for i in range(len(headers))]
        # Skip fully empty rows
        if any(v is not None and str(v).strip() != "" for v in row):
            rows.append(row)
            
    return headers, rows

def get_numeric_and_text_cols(headers, rows):
    numeric_cols = []
    text_cols = []
    
    for i, h in enumerate(headers):
        is_numeric = True
        val_count = 0
        for r in rows:
            val = r[i]
            if val is not None and str(val).strip() != "":
                val_count += 1
                try:
                    float(str(val).replace(",", "").strip())
                except ValueError:
                    is_numeric = False
                    break
        if is_numeric and val_count > 0:
            numeric_cols.append(h)
        else:
            text_cols.append(h)
            
    return numeric_cols, text_cols

def generate_chart(file_path, chart_type, output_image_path, x_col, y_col):
    headers, rows = parse_spreadsheet(file_path)
    
    if x_col not in headers or y_col not in headers:
        raise ValueError(f"Selected columns not found in file. Headers: {', '.join(headers)}")
        
    x_idx = headers.index(x_col)
    y_idx = headers.index(y_col)
    
    # Extract x and y data
    x_data = []
    y_data = []
    for r in rows:
        x_val = r[x_idx]
        y_val = r[y_idx]
        if x_val is not None and y_val is not None and str(x_val).strip() != "" and str(y_val).strip() != "":
            try:
                y_float = float(str(y_val).replace(",", "").strip())
                x_data.append(str(x_val).strip())
                y_data.append(y_float)
            except ValueError:
                continue
                
    if not x_data:
        raise ValueError(f"No numeric values found in column '{y_col}' to plot.")
        
    plt.figure(figsize=(10, 6))
    
    chart_type = chart_type.lower()
    if chart_type == "bar":
        # Limit labels length to avoid cluttering X axis
        x_labels = [label[:15] + "..." if len(label) > 15 else label for label in x_data]
        plt.bar(x_labels, y_data, color="#4f46e5", edgecolor="none")
        plt.xlabel(x_col, fontweight='bold', fontsize=12)
        plt.ylabel(y_col, fontweight='bold', fontsize=12)
        plt.xticks(rotation=45, ha='right')
    elif chart_type == "line":
        x_labels = [label[:15] + "..." if len(label) > 15 else label for label in x_data]
        plt.plot(x_labels, y_data, marker='o', linewidth=2.5, color="#10b981")
        plt.xlabel(x_col, fontweight='bold', fontsize=12)
        plt.ylabel(y_col, fontweight='bold', fontsize=12)
        plt.xticks(rotation=45, ha='right')
    elif chart_type == "pie":
        # Group duplicates
        grouped = {}
        for x, y in zip(x_data, y_data):
            grouped[x] = grouped.get(x, 0.0) + y
            
        x_grouped = list(grouped.keys())
        y_grouped = list(grouped.values())
        
        # Limit to 10 slices for readability
        if len(x_grouped) > 10:
            top_x = x_grouped[:9]
            top_y = y_grouped[:9]
            other_sum = sum(y_grouped[9:])
            x_grouped = top_x + ["Other"]
            y_grouped = top_y + [other_sum]
            
        plt.pie(y_grouped, labels=x_grouped, autopct='%1.1f%%', startangle=140,
                colors=["#4f46e5", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#3b82f6", "#14b8a6"])
        plt.axis('equal')
        
    plt.title(f"{y_col} by {x_col}", fontsize=14, fontweight='bold', pad=15)
    plt.tight_layout()
    plt.savefig(output_image_path, dpi=300)
    plt.close()
