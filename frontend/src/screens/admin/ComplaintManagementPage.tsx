import { useEffect, useMemo, useState } from 'react';
import { Plus, Search, Edit2, Trash2, Tag } from 'lucide-react';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import EmptyState from '../../components/common/EmptyState';
import ErrorState from '../../components/common/ErrorState';
import Modal from '../../components/common/Modal';
import * as complaintsApi from '../../services/api/complaints';
import type { ChiefComplaint } from '../../types';

export default function ComplaintManagementPage() {
  const [searchTerm, setSearchTerm] = useState('');
  const [complaints, setComplaints] = useState<ChiefComplaint[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [editingComplaint, setEditingComplaint] = useState<ChiefComplaint | null>(null);
  const [formData, setFormData] = useState({
    name: '',
    nameEn: '',
    category: '',
    description: '',
    isActive: true,
  });
  const [isSubmitting, setIsSubmitting] = useState(false);

  const loadComplaints = async () => {
    setIsLoading(true);
    setError('');
    try {
      const response = await complaintsApi.getComplaints({ limit: 100 });
      setComplaints(response.data);
    } catch {
      setError('無法載入主訴模版');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadComplaints();
  }, []);

  const filteredComplaints = useMemo(() => {
    if (!searchTerm.trim()) return complaints;
    const keyword = searchTerm.trim().toLowerCase();
    return complaints.filter((item) =>
      [item.name, item.nameEn, item.category, item.description]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(keyword)),
    );
  }, [complaints, searchTerm]);

  const openCreateModal = () => {
    setEditingComplaint(null);
    setFormData({
      name: '',
      nameEn: '',
      category: '',
      description: '',
      isActive: true,
    });
    setShowModal(true);
  };

  const openEditModal = (complaint: ChiefComplaint) => {
    setEditingComplaint(complaint);
    setFormData({
      name: complaint.name,
      nameEn: complaint.nameEn || '',
      category: complaint.category,
      description: complaint.description || '',
      isActive: complaint.isActive,
    });
    setShowModal(true);
  };

  const handleSubmit = async () => {
    if (!formData.name.trim() || !formData.category.trim()) return;

    setIsSubmitting(true);
    try {
      if (editingComplaint) {
        await complaintsApi.updateComplaint(editingComplaint.id, {
          name: formData.name.trim(),
          nameEn: formData.nameEn.trim() || undefined,
          category: formData.category.trim(),
          description: formData.description.trim() || undefined,
          isActive: formData.isActive,
        });
      } else {
        await complaintsApi.createComplaint({
          name: formData.name.trim(),
          nameEn: formData.nameEn.trim() || undefined,
          category: formData.category.trim(),
          description: formData.description.trim() || undefined,
          isActive: formData.isActive,
          displayOrder: complaints.length + 1,
        });
      }

      setShowModal(false);
      await loadComplaints();
    } catch {
      setError('儲存主訴失敗');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDelete = async (complaintId: string) => {
    try {
      await complaintsApi.deleteComplaint(complaintId);
      await loadComplaints();
    } catch {
      setError('刪除主訴失敗');
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-surface-900">主訴模版管理</h1>
          <p className="text-surface-500 text-sm mt-1">管理病患端可選擇的預設主訴項目與分類。</p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded-xl hover:bg-primary-700 transition-colors shadow-sm font-medium" onClick={openCreateModal}>
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

        {error ? <ErrorState message={error} onRetry={loadComplaints} /> : null}

        {isLoading ? (
          <LoadingSpinner fullPage />
        ) : filteredComplaints.length === 0 ? (
          <EmptyState title="無主訴資料" message="目前沒有符合條件的主訴項目" />
        ) : (
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
                {filteredComplaints.map((item) => (
                  <tr key={item.id} className="hover:bg-surface-50 transition-colors">
                    <td className="py-4 px-6 font-medium text-surface-900">{item.name}</td>
                    <td className="py-4 px-6 text-surface-600">{item.nameEn || '-'}</td>
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
                        <button className="p-1.5 text-surface-400 hover:text-primary-600 bg-surface-100 hover:bg-primary-50 rounded-lg transition-colors" onClick={() => openEditModal(item)}>
                          <Edit2 className="h-4 w-4" />
                        </button>
                        <button className="p-1.5 text-surface-400 hover:text-red-600 bg-surface-100 hover:bg-red-50 rounded-lg transition-colors" onClick={() => handleDelete(item.id)}>
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <Modal
        visible={showModal}
        onClose={() => setShowModal(false)}
        title={editingComplaint ? '編輯主訴' : '新增主訴'}
        footer={(
          <>
            <button className="btn-secondary" onClick={() => setShowModal(false)}>取消</button>
            <button className="btn-primary" onClick={handleSubmit} disabled={isSubmitting}>
              {isSubmitting ? '儲存中...' : '儲存'}
            </button>
          </>
        )}
      >
        <div className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-surface-700">主訴名稱</label>
            <input className="input-base w-full" value={formData.name} onChange={(e) => setFormData((prev) => ({ ...prev, name: e.target.value }))} />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-surface-700">英文名稱</label>
            <input className="input-base w-full" value={formData.nameEn} onChange={(e) => setFormData((prev) => ({ ...prev, nameEn: e.target.value }))} />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-surface-700">分類</label>
            <input className="input-base w-full" value={formData.category} onChange={(e) => setFormData((prev) => ({ ...prev, category: e.target.value }))} />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-surface-700">描述</label>
            <textarea className="input-base min-h-[96px] w-full resize-y" value={formData.description} onChange={(e) => setFormData((prev) => ({ ...prev, description: e.target.value }))} />
          </div>
          <label className="flex items-center gap-2 text-sm text-surface-700">
            <input type="checkbox" checked={formData.isActive} onChange={(e) => setFormData((prev) => ({ ...prev, isActive: e.target.checked }))} />
            啟用此主訴
          </label>
        </div>
      </Modal>
    </div>
  );
}
