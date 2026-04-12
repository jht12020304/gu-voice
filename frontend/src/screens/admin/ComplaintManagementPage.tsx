import { useState } from 'react';
import { Plus, Search, Edit2, Trash2, Tag, AlertTriangle } from 'lucide-react';

export default function ComplaintManagementPage() {
  const [searchTerm, setSearchTerm] = useState('');

  // Mock data
  const complaints = [
    { id: 1, name: '血尿', nameEn: 'Bloody Urine', category: '泌尿系統', isDefault: true, isActive: true },
    { id: 2, name: '腰痛', nameEn: 'Flank Pain', category: '泌尿系統', isDefault: true, isActive: true },
    { id: 3, name: '排尿困難', nameEn: 'Dysuria', category: '排尿障礙', isDefault: true, isActive: true },
    { id: 4, name: '頻尿', nameEn: 'Frequent Urination', category: '排尿障礙', isDefault: false, isActive: true },
    { id: 5, name: '急尿', nameEn: 'Urgency', category: '排尿障礙', isDefault: false, isActive: false },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-surface-900">主訴模版管理</h1>
          <p className="text-surface-500 text-sm mt-1">管理病患端可選擇的預設主訴項目與紅旗警示關聯。</p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded-xl hover:bg-primary-700 transition-colors shadow-sm font-medium">
          <Plus className="h-4 w-4" />
          新增主訴
        </button>
      </div>

      <div className="bg-white rounded-2xl shadow-sm border border-surface-200 overflow-hidden">
        <div className="p-4 border-b border-surface-200 bg-surface-50">
          <div className="relative max-w-md">
            <Search className="absolute left-3 top-2.5 h-5 w-5 text-surface-400" />
            <input
              type="text"
              placeholder="搜尋主訴名稱..."
              className="w-full pl-10 pr-4 py-2 border border-surface-200 rounded-xl focus:border-primary-500 focus:ring-1 focus:ring-primary-500 bg-white"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-surface-50 text-surface-500 text-sm border-b border-surface-200">
                <th className="py-3 px-6 font-medium">主訴名稱</th>
                <th className="py-3 px-6 font-medium">英文名稱</th>
                <th className="py-3 px-6 font-medium">分類</th>
                <th className="py-3 px-6 font-medium">預設顯示</th>
                <th className="py-3 px-6 font-medium">狀態</th>
                <th className="py-3 px-6 font-medium text-right">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-100">
              {complaints.map((item) => (
                <tr key={item.id} className="hover:bg-surface-50 transition-colors">
                  <td className="py-4 px-6">
                    <div className="font-medium text-surface-900 flex items-center gap-2">
                       {item.name}
                       {item.id === 1 && <AlertTriangle className="h-4 w-4 text-red-500" title="綁定嚴重紅旗警示" />}
                    </div>
                  </td>
                  <td className="py-4 px-6 text-surface-600">{item.nameEn}</td>
                  <td className="py-4 px-6">
                    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-surface-100 text-surface-700">
                      <Tag className="h-3 w-3" />
                      {item.category}
                    </span>
                  </td>
                  <td className="py-4 px-6">
                    {item.isDefault ? (
                      <span className="text-green-600 bg-green-50 px-2 py-1 rounded-md text-xs font-medium">是的</span>
                    ) : (
                      <span className="text-surface-400 text-xs">否</span>
                    )}
                  </td>
                  <td className="py-4 px-6">
                    <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${
                      item.isActive ? 'bg-primary-50 text-primary-700' : 'bg-surface-100 text-surface-500'
                    }`}>
                      {item.isActive ? '啟用中' : '已停用'}
                    </span>
                  </td>
                  <td className="py-4 px-6">
                    <div className="flex justify-end gap-2">
                      <button className="p-1.5 text-surface-400 hover:text-primary-600 bg-surface-100 hover:bg-primary-50 rounded-lg transition-colors">
                        <Edit2 className="h-4 w-4" />
                      </button>
                      <button className="p-1.5 text-surface-400 hover:text-red-600 bg-surface-100 hover:bg-red-50 rounded-lg transition-colors">
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
